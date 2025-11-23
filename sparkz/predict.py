"""
sparkz.predict
Gera previsões usando modelos treinados e persiste em MongoDB na coleção `forecast_demeter`.

Uso exemplo:
  SPARK_MASTER_URL=spark://... MONGO_URI="mongodb://..." MONGO_DB=demeter python sparkz/predict.py --horizons 1,3,24 --targets temperature,humidity

Observação: prevê com modelos diretos por horizonte (cada modelo prediz t+h diretamente).
"""
import os
import argparse
from datetime import datetime, timedelta

def get_env(name, default=None):
    return os.environ.get(name, default)

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizons', type=str, default='1', help='Comma-separated horizons in hours')
    parser.add_argument('--targets', type=str, default='temperature', help='Comma-separated targets')
    args = parser.parse_args(argv)

    horizons = [int(x) for x in args.horizons.split(',') if x]
    targets = [t.strip() for t in args.targets.split(',') if t.strip()]

    # Import PySpark here
    from pyspark.sql import SparkSession, Window
    from pyspark.sql import functions as F
    from pyspark.ml import PipelineModel
    from sparkz.utils import spark_config_for_mongo, mongo_read_options

    builder = SparkSession.builder.appName('Demeter-Forecast-Predict')
    master = get_env('SPARK_MASTER_URL')
    if master:
        builder = builder.master(master)
    builder = spark_config_for_mongo(builder)
    spark = builder.getOrCreate()

    sensors_coll = get_env('MONGO_COLLECTION_SENSORS') or 'readings'
    forecast_coll = get_env('MONGO_COLLECTION_FORECAST') or 'forecast_demeter'

    # Use helper to read with fallback
    from sparkz.utils import read_collection_with_fallback
    sensors_df = read_collection_with_fallback(spark, sensors_coll)

    sensors_df = sensors_df.withColumn('timestamp', F.col('timestamp').cast('timestamp'))

    # Build window to compute recent lags per silo
    window_desc = Window.partitionBy('siloId').orderBy(F.col('timestamp').desc())
    # compute last measurements and lags
    sensors_df = sensors_df.withColumn('last_temp', F.first('temperature').over(window_desc))
    sensors_df = sensors_df.withColumn('temp_lag_1', F.lag('temperature', 1).over(window_desc))
    sensors_df = sensors_df.withColumn('temp_lag_3', F.lag('temperature', 3).over(window_desc))
    sensors_df = sensors_df.withColumn('temp_lag_6', F.lag('temperature', 6).over(window_desc))
    sensors_df = sensors_df.withColumn('last_hum', F.first('humidity').over(window_desc))

    latest = sensors_df.withColumn('rank', F.row_number().over(window_desc)).filter(F.col('rank') == 1).drop('rank')

    # For each target and horizon, load model and predict
    results = []
    for target in targets:
        for h in horizons:
            model_dir = get_env(f'SPARK_MODEL_PATH_{target.upper()}_H{h}') or f'models/{target}_h{h}'
            try:
                model = PipelineModel.load(model_dir)
            except Exception as e:
                print(f'Could not load model {model_dir}: {e}')
                continue
            # Create a DataFrame with feature columns matching training (best-effort)
            from pyspark.ml.feature import VectorAssembler
            feat_cols = []
            for c in ['temp_lag_1','temp_lag_3','temp_lag_6','last_temp','last_hum']:
                if c in latest.columns:
                    feat_cols.append(c)
            if not feat_cols:
                print('No feature columns available for prediction; skipping')
                continue
            predict_df = latest.fillna({c:0 for c in feat_cols})
            asm = VectorAssembler(inputCols=feat_cols, outputCol='features')
            predict_df = asm.transform(predict_df)
            pred = model.transform(predict_df)
            # pred contains prediction column 'prediction'
            selected = pred.select('siloId', 'timestamp', 'prediction')
            # Convert to local Python list and write to MongoDB using pymongo for simplicity
            rows = selected.toPandas().to_dict(orient='records')

            # write with pymongo
            from pymongo import MongoClient
            mongo_uri = get_env('MONGO_URI')
            db_name = get_env('MONGO_DB')
            client = MongoClient(mongo_uri)
            db = client[db_name]
            coll = db[forecast_coll]
            now = datetime.utcnow()
            docs = []
            for r in rows:
                silo = r.get('siloId')
                timestamp = r.get('timestamp')
                pred_value = float(r.get('prediction')) if r.get('prediction') is not None else None
                ts_forecast = (timestamp if timestamp else now) + timedelta(hours=h)
                docs.append({
                    'siloId': silo,
                    'target': target,
                    'timestamp_forecast': ts_forecast,
                    'value_predicted': pred_value,
                    'horizon_hours': h,
                    'generated_at': now
                })
            if docs:
                coll.insert_many(docs)
                print(f'Inserted {len(docs)} predictions for target {target} horizon {h}')

    spark.stop()

if __name__ == '__main__':
    main()

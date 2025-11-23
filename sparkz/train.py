"""
sparkz.train
Treina modelos por variável alvo usando PySpark MLlib.

Como usar (exemplo):
  SPARK_MASTER_URL=spark://... MONGO_URI="mongodb://..." MONGO_DB=demeter python sparkz/train.py --horizons 1,3,24 --targets temperature,humidity

Observações:
  - Requer PySpark e o MongoDB Spark Connector (ou fallback via pymongo+pandas)
  - Salva modelos em `SPARK_MODEL_PATH_<TARGET>_H<horizon>` (variáveis de ambiente) ou em `models/<target>_h<h>.parquet`
"""
import os
import argparse
from datetime import timedelta

def get_env(name, default=None):
    return os.environ.get(name, default)

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--horizons', type=str, default='1', help='Comma-separated horizons in hours (e.g. 1,3,24)')
    parser.add_argument('--targets', type=str, default='temperature', help='Comma-separated target names')
    parser.add_argument('--silos', type=str, default=None, help='Optional comma-separated silo IDs to train')
    args = parser.parse_args(argv)

    horizons = [int(x) for x in args.horizons.split(',') if x]
    targets = [t.strip() for t in args.targets.split(',') if t.strip()]
    silos_filter = [s.strip() for s in args.silos.split(',')] if args.silos else None

    # Import PySpark only when running the job (avoid importing in backend runtime)
    from pyspark.sql import SparkSession, Window
    from pyspark.sql import functions as F
    from pyspark.ml import Pipeline
    from pyspark.ml.feature import VectorAssembler, StandardScaler
    from pyspark.ml.regression import RandomForestRegressor
    from sparkz.utils import spark_config_for_mongo, mongo_read_options

    app_name = get_env('SPARK_APP_NAME') or 'Demeter-Forecast-Train'
    builder = SparkSession.builder.appName(app_name)
    master = get_env('SPARK_MASTER_URL')
    if master:
        builder = builder.master(master)

    # Configure MongoDB connector options
    builder = spark_config_for_mongo(builder)
    spark = builder.getOrCreate()

    # Read collections
    sensors_coll = get_env('MONGO_COLLECTION_SENSORS') or 'readings'
    weather_coll = get_env('MONGO_COLLECTION_WEATHER') or 'meteorology'

    print('Lendo dados do MongoDB...')
    # Use helper that tries connector first, then fallback to pymongo+pandas
    from sparkz.utils import read_collection_with_fallback
    sensors_df = read_collection_with_fallback(spark, sensors_coll)
    weather_df = read_collection_with_fallback(spark, weather_coll)

    # Normalizar nomes de colunas esperadas
    # Assumindo campos: siloId, timestamp, temperature, humidity, co2, flammable_gases, luminosity_lux, luminosity_fire_flag
    df = sensors_df.withColumnRenamed('siloId', 'siloId')

    # Conversões de tipo
    df = df.withColumn('timestamp', F.col('timestamp').cast('timestamp'))
    for col in ['temperature', 'humidity', 'co2', 'flammable_gases', 'luminosity_lux']:
        if col in df.columns:
            df = df.withColumn(col, F.col(col).cast('double'))

    # Filtrar silos se solicitado
    if silos_filter:
        df = df.filter(F.col('siloId').isin(silos_filter))

    # Deduplication: keep one record per 5 minutes when all metrics identical
    window = Window.partitionBy('siloId').orderBy('timestamp')
    df = df.withColumn('prev_temp', F.lag('temperature').over(window))
    df = df.withColumn('prev_humidity', F.lag('humidity').over(window))
    df = df.withColumn('prev_co2', F.lag('co2').over(window))
    df = df.withColumn('time_diff_prev', (F.unix_timestamp('timestamp') - F.unix_timestamp(F.lag('timestamp').over(window))))

    # Keep rows where not identical to previous within IDENTICAL_READINGS_MIN_SECONDS, or first row
    min_secs = int(get_env('IDENTICAL_READINGS_MIN_SECONDS') or 300)
    df = df.filter((F.col('prev_temp').isNull()) |
                   (F.col('temperature') != F.col('prev_temp')) |
                   (F.col('time_diff_prev') > min_secs))

    # Feature engineering: create lags and moving averages per silo
    # Example lags: 1,3,6
    lags = [1,3,6]
    for lag in lags:
        df = df.withColumn(f'temp_lag_{lag}', F.lag('temperature', lag).over(window))
        df = df.withColumn(f'hum_lag_{lag}', F.lag('humidity', lag).over(window))

    # Moving averages: 30min/1h/3h windows (assuming readings frequent; adjust as needed)
    df = df.withColumn('ts_unix', F.unix_timestamp('timestamp'))
    df = df.withColumn('temp_ma_30m', F.avg('temperature').over(window.rangeBetween(-1800,0)))
    df = df.withColumn('temp_ma_1h', F.avg('temperature').over(window.rangeBetween(-3600,0)))

    # Join weather by nearest week or nearest timestamp; here we do a simple broadcast join on nearest date
    # TODO: improve join strategy (nearest hourly/daily interpolation)
    weather_df = weather_df.withColumn('timestamp', F.col('timestamp').cast('timestamp'))
    # For simplicity, join by date (day)
    df = df.withColumn('date', F.to_date('timestamp'))
    weather_df = weather_df.withColumn('date', F.to_date('timestamp'))
    df = df.join(weather_df.select('date', 'temperature as ext_temperature', 'humidity as ext_humidity'), on='date', how='left')

    # Drop rows with too many nulls
    df = df.dropna(subset=['temperature'])

    # Split temporally into train/val/test to avoid leakage
    # Compute timestamp bounds
    ts_col = F.unix_timestamp('timestamp')
    bounds = df.select(F.min(ts_col).alias('min_ts'), F.max(ts_col).alias('max_ts')).first()
    if bounds and bounds['min_ts'] is not None:
        min_ts = bounds['min_ts']
        max_ts = bounds['max_ts']
        span = max_ts - min_ts if max_ts and min_ts else None
    else:
        min_ts = None
        span = None

    # Train per target and per horizon
    for target in targets:
        if target not in df.columns:
            print(f'Warning: target {target} not present in data; skipping')
            continue
        for h in horizons:
            label_col = f'label_h{h}'
            # Create label as value at t + h hours
            df_label = df.withColumn(label_col, F.lead(target, h).over(window))
            train_df = df_label.dropna(subset=[label_col])
            # Select features
            feature_cols = [c for c in train_df.columns if c.startswith('temp_lag_') or c.startswith('hum_lag_') or c.startswith('temp_ma_')]
            if 'ext_temperature' in train_df.columns:
                feature_cols.append('ext_temperature')
            print(f'Training target={target} horizon={h} features={feature_cols} rows={train_df.count()}')

            assembler = VectorAssembler(inputCols=feature_cols, outputCol='features')
            scaler = StandardScaler(inputCol='features', outputCol='scaledFeatures')
            rf = RandomForestRegressor(featuresCol='scaledFeatures', labelCol=label_col, numTrees=50)
            pipeline = Pipeline(stages=[assembler, scaler, rf])

            model = pipeline.fit(train_df)

            # Evaluate on validation/test if available
            evaluator_rmse = None
            evaluator_mae = None
            try:
                from pyspark.ml.evaluation import RegressionEvaluator
                evaluator_rmse = RegressionEvaluator(labelCol=label_col, predictionCol='prediction', metricName='rmse')
                evaluator_mae = RegressionEvaluator(labelCol=label_col, predictionCol='prediction', metricName='mae')
                # Prepare a temporal split: last 15% as test
                if span:
                    cutoff = min_ts + int(span * 0.85)
                    test_df = train_df.filter(F.unix_timestamp('timestamp') >= cutoff)
                else:
                    test_df = train_df.sample(fraction=0.15)
                preds = model.transform(test_df)
                rmse = evaluator_rmse.evaluate(preds)
                mae = evaluator_mae.evaluate(preds)
            except Exception as e:
                print('Warning: could not evaluate model (evaluator missing or error):', e)
                rmse = None
                mae = None

            # Save model
            model_dir = get_env(f'SPARK_MODEL_PATH_{target.upper()}_H{h}') or f'models/{target}_h{h}'
            print(f'Saving model to {model_dir}')
            model.write().overwrite().save(model_dir)

            # Log metrics to MongoDB ml_metrics collection
            try:
                from pymongo import MongoClient
                mongo_uri = get_env('MONGO_URI')
                dbname = get_env('MONGO_DB')
                client = MongoClient(mongo_uri)
                dbm = client[dbname]
                metrics_coll = get_env('MONGO_COLLECTION_ML_METRICS') or 'ml_metrics'
                doc = {
                    'model_path': model_dir,
                    'target': target,
                    'horizon_hours': h,
                    'rmse': float(rmse) if rmse is not None else None,
                    'mae': float(mae) if mae is not None else None,
                    'trained_at': __import__('datetime').datetime.utcnow(),
                    'rows_train': train_df.count()
                }
                dbm[metrics_coll].insert_one(doc)
                print('Logged metrics to', metrics_coll)
            except Exception as e:
                print('Warning: could not write metrics to MongoDB:', e)

    spark.stop()

if __name__ == '__main__':
    main()

"""
sparkz.utils
Helpers para SparkSession e leitura/escrita do MongoDB.

Uso:
  - Os scripts em `sparkz/` usam este utilitário para criar a SparkSession
    com configuração do MongoDB via variáveis de ambiente.

NOTA: Este módulo é importado somente quando os jobs PySpark são executados
      via `spark-submit` ou `python sparkz/train.py` num ambiente com PySpark.
      Não importe este módulo no backend FastAPI (evita exigir pyspark no runtime do app).
"""
import os
from typing import Dict

def get_env(name: str, default=None):
    return os.environ.get(name, default)

def build_mongo_uri():
    # Expects MONGO_URI in the form mongodb://user:pass@host:port
    uri = get_env('MONGO_URI')
    db = get_env('MONGO_DB')
    if not uri:
        raise RuntimeError('MONGO_URI not set')
    if db:
        return f"{uri}/{db}?retryWrites=true&w=majority"
    return uri

def spark_config_for_mongo(spark_builder):
    """Configura o SparkSession builder para usar o MongoDB Spark Connector.
    Se o conector não estiver disponível, os scripts tentam fallback via PyMongo/Pandas.
    """
    mongo_uri = build_mongo_uri()
    # Assumes the spark-mongodb connector jar is provided via --packages
    spark_builder.config("spark.mongodb.input.uri", mongo_uri)
    spark_builder.config("spark.mongodb.output.uri", mongo_uri)
    return spark_builder

def mongo_read_options(collection: str) -> Dict[str, str]:
    db = get_env('MONGO_DB')
    uri = get_env('MONGO_URI')
    if not uri:
        raise RuntimeError('MONGO_URI missing')
    # The connector expects the full uri with database.collection
    return {"uri": f"{uri}/{db}.{collection}"}


def read_collection_with_fallback(spark, collection: str):
    """Tenta ler a coleção via MongoDB Spark Connector; se falhar, usa pymongo->pandas->spark.createDataFrame.
    Retorna um DataFrame Spark.
    """
    try:
        opts = mongo_read_options(collection)
        df = spark.read.format('mongo').options(**opts).load()
        return df
    except Exception as e:
        # Fallback via pymongo
        try:
            import pandas as pd
            from pymongo import MongoClient
            uri = get_env('MONGO_URI')
            dbname = get_env('MONGO_DB')
            client = MongoClient(uri)
            coll = client[dbname][collection]
            docs = list(coll.find({}))
            if not docs:
                # return empty spark dataframe
                return spark.createDataFrame(spark.sparkContext.emptyRDD(), schema=None)
            # Normalize ObjectId and dates for pandas
            dfp = pd.DataFrame(docs)
            # Convert ObjectId to string if present
            if '_id' in dfp.columns:
                dfp['_id'] = dfp['_id'].astype(str)
            # Create spark df
            sdf = spark.createDataFrame(dfp)
            return sdf
        except Exception as e2:
            raise RuntimeError(f'Failed to read collection {collection} via connector and fallback: {e}; fallback error: {e2}')

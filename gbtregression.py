# -*- coding: utf-8 -*-
"""gbtregression.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/16TAadZK8VYl1KKXdfVIm_jkvFwjlZfMU
"""

from pyspark.sql import SparkSession
from pyspark.sql.types import IntegerType, DoubleType
from pyspark.sql.functions import udf, col, dayofyear, month, year, when
from pyspark.ml import Pipeline
from pyspark.ml.feature import StringIndexer, VectorAssembler
from pyspark.ml.regression import GBTRegressor, RandomForestRegressor
from pyspark.ml.evaluation import RegressionEvaluator
from pyspark import SparkContext
import re

PYSPARK_CLI = True
if PYSPARK_CLI:
    sc = SparkContext.getOrCreate()
    spark = SparkSession(sc)

# Function to convert ISO 8601 durations to minutes
def parse_duration(duration):
    match = re.match(r'PT(\d+H)?(\d+M)?', duration)
    hours = int(match.group(1)[:-1]) if match.group(1) else 0
    minutes = int(match.group(2)[:-1]) if match.group(2) else 0
    return hours * 60 + minutes

# Register UDF
parse_duration_udf = udf(parse_duration, IntegerType())

# File location and type
file_location = "/use/skarri2/flights_LAX.csv"
file_type = "csv"
infer_schema = "true"
first_row_is_header = "true"
delimiter = ","

# Read the data
df = spark.read.format(file_type) \
  .option("inferSchema", infer_schema) \
  .option("header", first_row_is_header) \
  .option("sep", delimiter) \
  .load(file_location)

# Apply the UDF and other transformations
df = df.withColumn("flightDayOfYear", dayofyear(col("flightDate").cast("date")))
df = df.withColumn("travelDurationMin", parse_duration_udf(col("travelDuration")).cast(DoubleType()))
df = df.withColumn("flightMonth", month("flightDate"))
df = df.withColumn("flightYear", year("flightDate"))
df = df.withColumn("SearchDayoftheYear", dayofyear(col("searchDate").cast("date")))
df = df.na.fill(0)  # Fill nulls if any

# Drop unused columns
columns_to_drop = ["legID", "segmentsDepartureTimeEpochSeconds", "segmentsArrivalTimeEpochSeconds",
                   "segmentsArrivalAirportCode", "segmentsDepartureAirportCode", "segmentsAirlineName",
                   "segmentsAirlineCode", "segmentsEquipmentDescription", "segmentsDurationInSeconds",
                   "segmentsDistance", "segmentsCabinCode", "segmentsDistance", "segmentsDurationInSeconds",
                   "segmentsArrivalTimeRaw", "segmentsDepartureTimeRaw", "segmentsAirlineCode", "startingAirport"  "baseFare",]
df = df.drop(*columns_to_drop)

# Reducing cardinality for 'fareBasisCode' by retaining only top categories
top_categories = df.select("fareBasisCode").groupBy("fareBasisCode").count().orderBy("count", ascending=False).limit(50).rdd.flatMap(lambda x: x).collect()
df = df.withColumn("fareBasisCodeReduced", when(col("fareBasisCode").isin(top_categories), col("fareBasisCode")).otherwise("Other"))

# Indexing string columns including the reduced 'fareBasisCode'
indexer = StringIndexer(inputCols=["destinationAirport", "fareBasisCodeReduced"],
                        outputCols=["destinationAirportIdx", "fareBasisCodeIndexed"])
df = indexer.fit(df).transform(df)

# Assemble features
assembler = VectorAssembler(
    inputCols=[
        "flightDayOfYear",
        "elapsedDays",
        "isBasicEconomy",
        "isRefundable",
        "isNonStop",
        "destinationAirportIdx",
        "seatsRemaining",
        "totalTravelDistance",
        "travelDurationMin",
        "fareBasisCodeIndexed",
        "SearchDayoftheYear"
    ],
    outputCol="features"
)

# Split the data
splits = df.randomSplit([0.7, 0.3])
train = splits[0]
test = splits[1]

#GBT
gbt = GBTRegressor(labelCol="totalFare", featuresCol="features", maxIter=50, maxBins=2200)
# Pipeline setup
pipeline_gbt = Pipeline(stages=[assembler, gbt])

# Fit models
model_gbt = pipeline_gbt.fit(train)

# Predictions
predictions_gbt = model_gbt.transform(test)

# Evaluators for RMSE and R2
evaluator_rmse = RegressionEvaluator(labelCol="totalFare", predictionCol="prediction", metricName="rmse")
evaluator_r2 = RegressionEvaluator(labelCol="totalFare", predictionCol="prediction", metricName="r2")

# Evaluation results
rmse_gbt = evaluator_rmse.evaluate(predictions_gbt)
r2_gbt = evaluator_r2.evaluate(predictions_gbt)

print("GBT Results - RMSE: {}, R2: {}".format(rmse_gbt, r2_gbt))
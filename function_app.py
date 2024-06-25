import datetime
import logging
import os
import requests
from azure.identity import DefaultAzureCredential
import azure.functions as func
import pandas as pd
from io import StringIO
import json

app = func.FunctionApp()

def parseCSV(url):
    # Reads CSV file from URL and converts it to JSON
    response = requests.get(url)
    if response.status_code==200:
        csv_content = response.content.decode('utf-8')
        csv_df = pd.read_csv(StringIO(csv_content))

        json_rows = csv_df.to_dict(orient='records')
        return json_rows
    
import math

def clean_json(data):
    # recursively cleans the data to ensure all values are JSON serializable
    if isinstance(data, dict):
        return {key: clean_json(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [clean_json(element) for element in data]
    elif isinstance(data, float):
        if math.isfinite(data):
            return data
        else:
            return None
    elif isinstance(data, (bool, int, str)) or data is None:
        return data
    else:
        return str(data)


def get_cost_data(subscription_id, token):

    # Tells Azure to enerate a cost detail report of our subscription
    url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/generateCostDetailsReport?api-version=2023-11-01"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Get from 00:00 of day before to 23:59 of same day
    end_date = datetime.datetime.utcnow()
    start_date = end_date - datetime.timedelta(days=1)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date + datetime.timedelta(days=1) - datetime.timedelta(seconds=1)

    start_date_iso = start_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_date_iso = end_date.strftime('%Y-%m-%dT%H:%M:%SZ')

    body = {
        "timePeriod": {
            "start": start_date_iso,
            "end": end_date_iso
        },
    }

    response = requests.post(url, headers=headers, json=body)

    # If the request was successful get the follow up URL from headers
    if response.status_code == 202:
        url=response.headers["Location"]
        response = requests.get(url, headers=headers)

        # Retrieve CSV file and return the parsed JSON data back to the main function
        if response.status_code == 200:
            json=response.json()
            logging.info(json['manifest']['blobs'][0]['blobLink'])
            return parseCSV(json['manifest']['blobs'][0]['blobLink'])
            # if json.status == "Completed":
            #     logging.info(json.blobs[0].blobLink)
            #     return parseCSV(json.blobs[0].blobLink)
        else:
            logging.error("Failed to fetch AAAAAAAAAAAAA data: %s", response.text)
    else:
        logging.error("Failed to fetch cost data: %s", response.text)
        return None

def send_to_coralogix(log_data):
    # Retrieves the correct coralogix domain and private key from Azure application settings
    coralogix_domain = os.getenv('CORALOGIX_DOMAIN')
    coralogix_key = os.getenv('CORALOGIX_PRIVATE_KEY')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {coralogix_key}"
    }

    # Makes sure the JSON is serializable before sending it to Coralogix
    cleaned_data = clean_json(log_data)

    payload = {
        "applicationName": "AzureFunctionApp",
        "subsystemName": "CostManagement",
        "timestamp": int(datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).timestamp() * 1000),
        "severity": 3,
        "text": cleaned_data
    }

    response = requests.post(f"https://ingress.{coralogix_domain}/logs/v1/singles", json=payload, headers=headers)
    
    if response.status_code == 200:
        logging.info("Successfully sent data to Coralogix")
    else:
        logging.error("Failed to send data to Coralogix: %s", response.text)

@app.function_name(name="mytimer")
@app.schedule(schedule="0 0 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=False)
def test_function(mytimer: func.TimerRequest) -> None:

    subscription_id = os.getenv('SUBSCRIPTION_ID')
    if not subscription_id:
        logging.error("Environment variable 'SUBSCRIPTION_ID' is not set.")
        return

    try:
        credential = DefaultAzureCredential()
        logging.info("Attempting to obtain token using DefaultAzureCredential.")
        token = credential.get_token("https://management.azure.com/.default").token
        logging.info("Successfully obtained token.")
    except Exception as e:
        logging.error(f"Failed to obtain token: {e}")
        return
    
    cost_data = get_cost_data(subscription_id, token)
    #data=parseCSV("https://ccmreportstorageeastus3.blob.core.windows.net/armmusagedetailsreportdownloadcontainer/20240624/35588afc-3610-406b-a9ed-d2ed82a61910?skoid=14e0b2b1-409d-493e-ae68-af20bf01e934&sktid=975f013f-7f24-47e8-a7d3-abc4752bf346&skt=2024-06-24T06%3A39%3A00Z&ske=2024-06-25T06%3A39%3A00Z&sks=b&skv=2021-12-02&sv=2021-12-02&spr=https&st=2024-06-24T08%3A50%3A15Z&se=2024-06-24T20%3A55%3A15Z&sr=b&sp=r&sig=Ya8i0GaZZosNhqNH7LHwA2Dg1T1YiOxISs%2B58ZHpvX4%3D")
    for row in cost_data:
        send_to_coralogix(row)


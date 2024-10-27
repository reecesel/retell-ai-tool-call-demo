'''
Copyright 2024 Reece Piccolo-Sellin

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
'''

# *********
# Core FastAPI
# *********

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse   

# *********
# Core services and support
# *********
import json
import requests

from retell import Retell

# *********
# Modules
# *********

from .settings import *

# *********
# Logging
# *********

import logging
from logging.handlers import WatchedFileHandler

# Initial setup for root logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.propagate = False


handler = WatchedFileHandler(filename=logfile_path_and_filename)
handler.setLevel(logging.INFO) # Set level to INFO
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

debug_handler = handler  # Initialize debug_handler as handler

# If debug_logfile_path_and_filename is set, create a separate debug_handler
if 'debug_logfile_path_and_filename' in globals():
    debug_handler = WatchedFileHandler(filename=debug_logfile_path_and_filename)
    debug_handler.setLevel(logging.DEBUG) # Set level to DEBUG
    debug_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    debug_handler.setFormatter(debug_formatter)

logger.addHandler(handler)
logger.addHandler(debug_handler)
logger.info('Root logging initialized')

# Other custom loggers
loggers = ['gunicorn', 'uvicorn', 'fastapi', 'root']

for log in loggers:
    custom_logger = logging.getLogger(log)
    custom_logger.propagate = False
    custom_logger.addHandler(handler)
    if log in ['uvicorn', 'fastapi', 'root']:
        custom_logger.setLevel(logging.DEBUG)
        custom_logger.addHandler(debug_handler)
    else:
        custom_logger.setLevel(logging.INFO)

logger.info('FastAPI, Gunicorn and Uvicorn logging initialized')

# *********
# Retell AI
# *********

retell = Retell(api_key=RETELL_API_KEY)

# *********
# Launch FastAPI
# *********

app = FastAPI(debug=False, docs_url=None, redoc_url=None, openapi_url = None)

# *********
# FastAPI Routes
# *********

# Root route
@app.get("/")
async def root_route(request: Request):
    logger.debug(f'Root route accessed: {request.url.hostname}')
    return JSONResponse(content={"message": "jgrobo-demo"})


# *********
# System ROUTES
# *********

###
# Retell verification
# 
# This approach is as documented at https://docs.retellai.com/features/webhook#verifying-webhook
# and is current as of 26 October 2024
###

async def verify_retell_request(request: Request):
    post_data = await request.json()
    valid_signature = retell.verify(
        json.dumps(post_data, separators=(",", ":")),
        api_key=str(RETELL_API_KEY),
        signature=str(request.headers.get("X-Retell-Signature")),
    )
    return valid_signature

###
#
# An example Retell webhook handler with signature verification.  Keep in mind for added
# security you can allowlist the Retell IP address, which as of 26 October 2024 is: 
# 100.20.5.228
#
##

@app.post("/retell/webhook")
async def retell_webhook(request: Request):
    try:
        valid_signature = verify_retell_request(request)
        if not valid_signature:
            logger.critical(f"retell_webhook received Unauthorized Retell Webhook: {post_data}")
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        else:
            post_data = await request.json()
            event_type = post_data["event"]
            logger.debug(f"retell_webhook received {event_type} webhook")   

            return JSONResponse(status_code=200, content={})
    
    except Exception as err:
        logger.error(f"retell_webhook threw exception: {err}", exc_info=True)
        return JSONResponse(
            status_code=500, content={"message": "Internal Server Error"}
        )

###
#
# Here is an example tool call.  
#
##

#
# Function to fetch NHL standings and find team stats by name using NHL's public API
#
def get_team_stats(team_identifier):
    # URL to fetch the current NHL standings
    url = "https://api-web.nhle.com/v1/standings/now"

    # Make the GET request to the NHL API
    response = requests.get(url)

    # Check if the request was successful
    if response.status_code != 200:
        return f"Error fetching data: {response.status_code}"

    # Parse the JSON response
    data = response.json()
    team_identifier_lower = team_identifier.lower()

    # Iterate through each team in the standings
    for team in data.get("standings", []):
        # Normalize fields to lowercase for comparison
        place_name = team["placeName"]["default"].lower()
        team_common_name = team["teamCommonName"]["default"].lower()
        team_name = team["teamName"]["default"].lower()
        team_name_fr = team["teamName"].get("fr", "").lower()

        # Check if the identifier is part of any of these team details
        if (place_name in team_identifier_lower or
            team_common_name in team_identifier_lower or
            team_name in team_identifier_lower or
            team_name_fr in team_identifier_lower):

            # Extract the desired stats
            team_stats = {
                "Team Name": team["teamName"]["default"],
                "Games Played": team["gamesPlayed"],
                "Wins": team["wins"],
                "Losses": team["losses"],
                "OT Losses": team["otLosses"],
                "Points": team["points"],
                "Points Percentage": team["pointPctg"]
            }

            return team_stats
    
    # If no matching team is found
    return None

@app.post("/retell/example-tool-call")
async def example_tool_call(request: Request):
    try:
        valid_signature = verify_retell_request(request)

        if not valid_signature:
            logger.critical(f"example_tool_call received Unauthorized Retell Webhook: {post_data}")
            return JSONResponse(status_code=401, content={"message": "Unauthorized"})
        else:
            post_data = await request.json()

            # Tool call arguments are stored in a dictionary called "args"
            args = post_data.get("args", {})
            team_identifier = args.get("team_identifier")
            team_stats = get_team_stats(team_identifier)

            # Return a response to the LLM
            if team_stats:
                # if we got a server error, it'll be a string like "Error fetching data: {response.status_code}"
                if isinstance(team_stats, str):
                    logger.error(f"example_tool_call could not load NHL data from API: {team_stats}")
                    return {"message": "something went wrong fetching stats"}
                else:
                    return {"message": "success", "team_stats": team_stats}
            else:
                return {"message": "could not find that team's stats; team may not exist -- have user try again"}
            
    except Exception as e:
        logger.error(f"Failed to test tool call", exc_info=True)
        return {"message": "error"}
    

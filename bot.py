import asyncio, json, requests, os
from datetime import datetime
from twitchio.ext import commands

# User-defined constants
DONATION_CURRENCY = '$' # Use the currency's symbol (ie. € for euros)
MININUM_DONATION = 0 # In the campaign's currency (ie. dollars)
API_POLL_RATE = 5 # In seconds

# Twitch bot class (TwitchIO)
class Bot(commands.Bot):
    # Saved credentials
    credentials = None
    channels = None
    campaign_id = None 
    auth_header = None

    # Other class variables
    donation_queue = []
    last_donation_id = None
    attempted_refresh = False

    # Getting credentials from json file
    def load_creds(self):
        timestamp = datetime.now().strftime("%H:%M:%S")
        csd = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(csd, "credentials.json")
        try:
            creds_file = open(path, 'r')
            if creds_file is not None:
                return json.load(creds_file)
            else:
                print(f"[{timestamp}] Could not read from credentials.json. Reason: File is empty")
        except:
            print(f"[{timestamp}] Could not read from credentials.json. Reason: File not found")


    def __init__(self):
        self.credentials = self.load_creds()
        self.update_access_token()
        self.campaign_id = self.get_campaign_id()
        self.get_last_donation_id()
        
        super().__init__(
            token = self.credentials['twitch_access_token'],
            prefix = '!',
            initial_channels = self.credentials['twitch_channel_names']
        )
        self.loop.create_task(self.process_tiltify_api_call())

    async def event_ready(self):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.channels = list(map(lambda c : self.get_channel(c), self.credentials['twitch_channel_names']))
        print(f"[{timestamp}] Twitch bot running.")

    # Get an access token from Tiltify by authenticating with our client details
    def auth_tiltify(self):
        timestamp = datetime.now().strftime("%H:%M:%S")

        url = "https://v5api.tiltify.com/oauth/token"
        params = {
            'client_id': self.credentials['tiltify_client_id'], 
            'client_secret': self.credentials['tiltify_client_secret'],
            'grant_type': 'client_credentials',
            'scope': 'public'
        }
        resp = requests.post(url, json = params)

        if resp.status_code == requests.codes.ok:
            return resp.json()['access_token']
        else:
            print(f"[{timestamp}] ERROR: Could not authenticate with Tiltify. Double check your credentials.")
            return None
        
    # Requests a new access token from Tiltify and updates the authorization header
    def update_access_token(self):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Requesting Tiltify access token...")

        token_resp = self.auth_tiltify()
        if token_resp is not None:
            self.auth_header = {'Authorization': 'Bearer ' + token_resp}
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] Successfully obtained Tiltify access token.")
        else:
            print(f"[{timestamp}] ERROR: Tiltify access token could not be obtained. Double check your credentials.")

    # Returns campaign ID from user slug and campaign slug
    def get_campaign_id(self):
        timestamp = datetime.now().strftime("%H:%M:%S")
        url = f"https://v5api.tiltify.com/api/public/campaigns/by/slugs/{self.credentials['tiltify_user_slug']}/{self.credentials['tiltify_campaign_slug']}"
        resp = requests.get(url, headers = self.auth_header)
        if resp.status_code == requests.codes.ok:
            return resp.json()['data']['id']
        else:
            print(f"[{timestamp}] ERROR: Campaign data could not be obtained from Tiltify. Something might be wrong with the API.")
            return None
    
    # Gets ID of last donation for checking purposes on startup
    def get_last_donation_id(self):
        url = f"https://v5api.tiltify.com/api/public/campaigns/{self.campaign_id}/donations"
        resp = requests.get(url, headers = self.auth_header, params = {'limit': 2})
        timestamp = datetime.now().strftime("%H:%M:%S")

        if resp.status_code == requests.codes.ok:
            self.last_donation_id = resp.json()['data'][0]['id']
        else:
            print(f"[{timestamp}] ERROR: Donation data could not be obtained from Tiltify. Something might be wrong with the API.")
        
    # Returns formatted donation message for Twitch chat
    def format_message(self, donation):
        donation_amount = float(donation['amount']['value'])
        donation_message = f"We have a {DONATION_CURRENCY}{donation_amount:,.2f} donation from {donation['donor_name']}"
        # Don't attach a donation message if there is none
        if donation['donor_comment'] is not None and donation['donor_comment'] != 'None':
            donation_message += f" with the comment \"{donation['donor_comment']}\""
        return donation_message
    
    # Searches for new donations by ID matching, and queues them for processing
    def check_donations(self):        
        url = f"https://v5api.tiltify.com/api/public/campaigns/{self.campaign_id}/donations"
        resp = requests.get(url, headers = self.auth_header)

        # In case we get multiple donations in a single update, we add all of them to a queue
        if resp.status_code == requests.codes.ok:
            self.attempted_refresh = False
            for donation in resp.json()['data']:
                donation_amount = float(donation['amount']['value'])
                if donation['id'] != self.last_donation_id and donation_amount >= MININUM_DONATION:
                    self.donation_queue.append(donation)
                    return True
                else:
                    break
        else:
            timestamp = datetime.now().strftime("%H:%M:%S")
            # We might need to get a new Tiltify access token if we're getting an error
            if self.attempted_refresh == False:
                print(f"[{timestamp}] Attempting to renew Tiltify authentication...")
                self.update_access_token()
                self.attempted_refresh = True
                self.check_donations()
            else:
                print(f"[{timestamp}] ERROR: Donation data could not be obtained from Tiltify. Something might be wrong with the API.")
        return False
    
    # Scheduled task for checking donations
    async def process_tiltify_api_call(self):
        while True:
            await asyncio.sleep(API_POLL_RATE)
            if self.check_donations():
                for donation in self.donation_queue:
                    for channel in self.channels:
                        await channel.send(self.format_message(donation))
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{timestamp}] Donation {donation['id']} processed")
                    self.last_donation_id = donation['id']
                self.donation_queue = []

# Run the Twitch bot.
bot = Bot()
bot.run()

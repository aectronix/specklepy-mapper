import json
import logging
import requests
import time

from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account
from specklepy.api import operations
from specklepy.transports.server import ServerTransport
from specklepy.serialization.base_object_serializer import BaseObjectSerializer

class SpeckleWrapper():

	def __init__(self, host="https://app.speckle.systems"):

		logger = logging.getLogger('speckle.client')
		self.log = logger
		self.log.setLevel(logging.WARNING)
		self.host = host
		self.client = None
		self.token = None
		self.transport = None

		self.connect();

	def connect(self):

		try:
			client = SpeckleClient(self.host)
			account = get_default_account()
			client.authenticate_with_account(account)
			if account and client:
				self.token = account.token
				self.client = client
				self.log.warning(f'Connected with credentials: $y({client.user.account.userInfo})')
		except Exception as e:
			raise e

	def retrieve(self, streamId, commitId):

		commit = self.client.commit.get(streamId, commitId)
		transport = ServerTransport(client=self.client, stream_id=streamId)
		if transport:
			self.transport = transport
			result = operations.receive(commit.referencedObject, self.transport)

		return result

	def publish(self, obj, branch, message, retries=10, delay=3):

		bos = BaseObjectSerializer()
		base = obj

		for attempt in range(retries):
			try:
				obj_updated = operations.send(obj, [self.transport])
				commit = self.client.commit.create(
				    'aeb487f0e6',
				    obj_updated,
				    branch_name = branch,
				    message = message
				)
				print (f'"{message}" has been published')
				return commit
			except Exception as e:
				print(f'Attempt {attempt + 1} failed: {e}')
				if attempt < retries - 1:
					time.sleep(delay)
				else:
					raise

	def query(self, query, variables):
	    """
	    Sends a GraphQL query to the Speckle server and returns the response.

	    Args:
	        query (str): The GraphQL query.
	        variables (dict, optional): The variables for the GraphQL query. Defaults to None.

	    Returns:
	        dict: The response data if the request is successful, None otherwise.
	    """
	    url = f"{self.host}/graphql"
	    payload = {"query": query, "variables": variables}
	    headers = {"Authorization": self.token, "Content-Type": "application/json"}

	    response = requests.post(url, json=payload, headers=headers)
	    return response.json() if response.status_code == 200 else None
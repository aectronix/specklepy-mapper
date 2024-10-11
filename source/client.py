import json
import logging
import requests
import time

from gql.transport.requests import log as gql_logger

from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account
from specklepy.api import operations
from specklepy.transports.server import ServerTransport
from specklepy.serialization.base_object_serializer import BaseObjectSerializer

from .logging import LogWrapper

class SpeckleWrapper():

	def __init__(self, host="https://app.speckle.systems"):

		self.log = LogWrapper.get_logger('speckle.client')
		gql_logger.setLevel(self.log.getEffectiveLevel()+10) # skip requests body

		self.host = host
		self.client = None
		self.token = None
		self.transport = None
		self.gql = None

		self.connect();

	def connect(self):

		try:
			client = SpeckleClient(self.host)
			account = get_default_account()
			client.authenticate_with_account(account)
			if account and client:
				self.token = account.token
				self.client = client
				self.gql = SpeckleGQL(self.host, self.token)
				self.log.info(f'Connected with credentials: $y({client.user.account.userInfo})')
		except Exception as e:
			raise e

	def retrieve(self, streamId, commitId):

		self.log.info(f'Receiving referencedObject, streamId: $m({streamId}), commitId: $m({commitId})')
		commit = self.client.commit.get(streamId, commitId)
		transport = ServerTransport(client=self.client, stream_id=streamId)
		if transport:
			self.transport = transport
			result = operations.receive(commit.referencedObject, self.transport)

		return result

	def publish(self, obj, projectId, branch, message, retries=10, delay=3):

		self.log.info(f'Publishing commit, branch: $y("{branch}"), message: $y("{message}")...')
		bos = BaseObjectSerializer()
		base = obj

		for attempt in range(retries):
			try:
				obj_updated = operations.send(obj, [self.transport])
				commit = self.client.commit.create(
				    projectId,
				    obj_updated,
				    branch_name = branch,
				    message = message
				)
				self.log.info(f'Published successfully')
				return commit
			except Exception as e:
				self.log.error(f'Attempt $m({attempt + 1}) failed: {e}')
				if attempt < retries - 1:
					time.sleep(delay)
				else:
					raise

	def query(self, query, *args):
		method = getattr(self.gql, query, None)
		if callable(method):
			return method(*args)
		else:
			self.log.error(f'Could not call such query: $y("{query}")')

class SpeckleGQL():

	def __init__(self, host, token):
		self.host = host
		self.token = token
		self.log = LogWrapper.get_logger('speckle.client.gql')

	def execute(self, query, variables):
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

	def get_level_data(self, projectId, objectId, idx):
		"""
		Hope this is temporary solution and we'll be able to fetch levels from info section.
		"""
		query = """
			query Object($objectId: String!, $projectId: String!, $query: [JSONObject!], $select: [String], $orderBy: JSONObject, $depth: Int!, $limit: Int!) {
			  project(id: $projectId) {
			    object(id: $objectId) {
			      children(query: $query, select: $select, orderBy: $orderBy, depth: $depth, limit: $limit) {
			        totalCount
			        objects {
			          data
			        }
			      }
			    }
			  }
			}
		"""
		variables = {
			"projectId": projectId,
			"objectId": objectId,
			"query": [
				{
				  "field": "level.index",
				  "value": idx,
				  "operator": "="
				}
			],
			"select": [
				"level.id",
				"level.name",
				"level.index",
				"level.elevation"
			],
			"orderBy": {
				"field": "level.index"
			},
			"depth": 3,
			"limit": 1
		}

		response = self.execute(query, variables)
		result = response['data']['project']['object']['children']['objects']

		return result[0]['data']['level'] if result else None

	def get_total_count(self, projectId, objectId, speckle_type):
		operator = '!=' if speckle_type == None else '='
		query = """
			query Object($objectId: String!, $projectId: String!, $query: [JSONObject!], $select: [String], $orderBy: JSONObject) {
			  project(id: $projectId) {
			    object(id: $objectId) {
			      children(query: $query, select: $select, orderBy: $orderBy) {
			        totalCount
			      }
			    }
			  }
			}
		"""
		variables = {
			"projectId": projectId,
			"objectId": objectId,
			"query": [
				{
				  "field": "speckle_type",
				  "value": speckle_type,
				  "operator": operator
				}
			],
			"select": [
				"speckle_type"
			]
		}

		response = self.execute(query, variables)
		result = response['data']['project']['object']['children']['totalCount']
		return result

	def get_object_data(self, projectId, objectId):
		query = """
			query Object($objectId: String!, $projectId: String!) {
			  project(id: $projectId) {
			    object(id: $objectId) {
			      id
			      data
			    }
			  }
			}
		"""
		variables = {
			"projectId": projectId,
			"objectId": objectId
		}

		response = self.execute(query, variables)
		result = response['data']['project']['object']['data']
		return result
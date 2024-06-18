from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account
from specklepy.api import operations
from specklepy.transports.server import ServerTransport
from specklepy.serialization.base_object_serializer import BaseObjectSerializer

class SpeckleWrapper():

	def __init__(self, host="https://app.speckle.systems"):

		self.host = host
		self.client = None
		self.transport = None

		self.connect();

	def connect(self):

		try:
			client = SpeckleClient(self.host)
			account = get_default_account()
			client.authenticate_with_account(account)
			if client:
				self.client = client
				print(f'Connected to Speckle: {client}')
		except Exception as e:
			raise e

	def retrieve(self, streamId, commitId):

		commit = self.client.commit.get(streamId, commitId)
		transport = ServerTransport(client=self.client, stream_id=streamId)
		if transport:
			self.transport = transport
			result = operations.receive(commit.referencedObject, self.transport)

		return result

	def publish(self, obj, message):

		bos = BaseObjectSerializer()
		base = obj
		obj_updated = operations.send(base, [self.transport])

		commit = self.client.commit.create(
		    'aeb487f0e6',
		    obj_updated,
		    branch_name = 'column',
		    message = message
		)
import json
import math
import os
import re

from abc import ABC, abstractmethod
from specklepy.objects.base import Base
from specklepy.objects.other import Collection
from specklepy.objects.geometry import *
from specklepy.serialization.base_object_serializer import BaseObjectSerializer

from .logging import LogWrapper

class TranslatorFactory:

	@staticmethod
	def get(translator, client, speckle_object=None, wrapper=None, **parameters):
		translators = {
			'Archicad2Revit': TranslatorArchicad2Revit,
		}
		return translators[translator](client, speckle_object, wrapper, **parameters)

class Translator(ABC):

	def __init__(self, client, speckle_object=None, wrapper=None, **parameters):
		self.log = None
		self.client = client
		self.object = speckle_object
		self.wrapper = wrapper

	def add_collection(self, name, typename, **parameters):
		collection = Collection()
		collection.name = name
		collection.collectionType = typename
		collection.elements = []
		collection.id = collection.get_id(decompose=True)
		return collection

	def add_point(self, x, y, z, units='m', traverse=False):
		pointObj = Point.from_list([x, y, z])
		pointObj.units = units
		if traverse:
			return BaseObjectSerializer().traverse_base(pointObj)[1]
		return pointObj

	def add_line(self, sx, sy, sz, ex, ey, ez, units='m', traverse=False):
		lineObj = Line()
		lineObj.start = self.add_point(sx, sy, sz, units=units)
		lineObj.end = self.add_point(ex, ey, ez, units=units)
		lineObj.units = units
		if traverse:
			return BaseObjectSerializer().traverse_base(lineObj)[1]
		return lineObj

	@staticmethod
	def get_schema(name):
		"""
		Loads translation schema.
		"""
		source = os.path.join(os.path.dirname(os.path.abspath(__file__)).replace('source', 'schemas'), name + '.json')
		with open(source, 'r') as file:
			schema = json.load(file)
		if schema:
			return schema

	@staticmethod
	def get_vector_direction(line):
		# delta
		dx = line['end']['x'] - line['start']['x']
		dy = line['end']['y'] - line['start']['y']
		# magnitude
		vm = math.sqrt(dx**2 + dy**2)
		# vector direction
		vx = dx / vm
		vy = dy / vm

		return {'x': vx, 'y': vy}

	@abstractmethod
	def map(self):
		"""
		Process the commit object and run mapping procedure
		"""
		pass

	def override_schema(self, entity, schema, parameters):
		"""
		Replaces existing object structure my the specified parameters of the given schema.
		Used to enable mapping options within the Revit environmnet while receving commits.
		"""
		for key, value in schema.items():
			if not isinstance(value, dict):
				entity[key] = parameters[key] if parameters and key in parameters else value
			else:
				if not key in entity:
					dummy = {} if isinstance(value, dict) else None
					entity[key] = dummy
				self.override_schema(entity[key], value, parameters[key])
		return entity

class TranslatorArchicad2Revit(Translator):

	def __init__(self, client, speckle_object=None, wrapper=None, **parameters):
		self.log = LogWrapper.get_logger('app.translator.a2r')
		self.client = client
		self.object = speckle_object
		self.wrapper = wrapper

		self.source = 'archicad'
		self.target = 'revit'
		self.schema = self.get_schema('remap_archicad2revit')
		self.categories = self.get_filtered_categories(parameters)
		self.collections = {}

	def get_filtered_categories(self, parameters):
		"""
		Retrieves category names that were specified manually. Otherwise, keep the full list.
		"""
		categories = parameters.get('categories', [key for key, value in self.schema['archicad'].items()])
		return categories

	def get_element_properties(self, speckle_object):
		"""
		Retrieves properties data for the given object.
		"""
		if 'elementProperties' in speckle_object:
			return speckle_object['elementProperties']
		else:
			self.log.warning(f"No properties found for {speckle_object['elementType']}: $m({speckle_object['id']})")
		return None

	def get_general_parameters(self, speckle_object):
		"""
		Retrieves tool-specific parameters (elevations, areas, volumes etc) for the given object.
		"""
		properties = self.get_element_properties(speckle_object)
		if properties:
			if 'General Parameters' in properties:
				return properties['General Parameters']
			else:
				self.log.warning(f"No parameters found for {speckle_object['elementType']}: $m({speckle_object['id']})")
		return {}

	def get_material_body(self, speckle_object):
		"""
		Retrieves the "body" of the given object, regarding it's structure.
		Could be the name of object building material, composite or profile.
		"""
		structure = {
		    'Basic': f"{speckle_object.get('buildingMaterialName')}",
		    'Composite': f"{speckle_object.get('compositeName')}",
		    'Profile': f"{speckle_object.get('profileName')}"
		}
		body = f"{structure[speckle_object['structure']]} ({speckle_object.get('thickness')}{speckle_object.get('units')})"
		return body if body else None

	def get_top_link(self, speckle_object, traverse=False):
		"""
		Retrieves the top link of the given element.
		"""
		general = self.get_general_parameters(speckle_object)
		top_level = None
		top_link = general.get('Top Link Story', '')
		top_link_ref = re.search(r'\+ (\d+)', top_link)
		if top_link_ref and top_link_ref.group(1) and hasattr(self.object, '@levels'):
			top_link_idx = speckle_object['level']['index'] + int(top_link_ref.group(1))
			for level in self.object['@levels']['elements']:
				if top_link_idx == level.index:
					if traverse:
						return BaseObjectSerializer().traverse_base(level)[1]
					return level
		return None

	def log_stats(self):
		"""
		Display some stats info
		"""
		total = self.client.query('get_total_count', 'aeb487f0e6', self.object.id, None)
		self.log.info(f"Commit object entities: $m({total})")
		for category in self.categories:
			count = self.client.query('get_total_count', 'aeb487f0e6', self.object.id, self.schema['archicad'][category]['speckle_type'])
			self.log.info(f'Total {category} objects: $m({count})')

	def map(self):
		# self.log_stats()
		# prepare the level structure before (!) the execution of remapping process
		# seems to be more stable to assign objects onto the existing levels
		# levels = self.add_collection('Levels', 'Levels Type')
		# self.object['@levels'] = levels
		# for i in range(-10, 20):
		# 	story = self.client.query('get_level_data', 'aeb487f0e6', self.object.id, i)
		# 	if story:
		# 		self.log.info(f'Level found: $y("{story['name']}"), $m({story['elevation']})')
		# 		level = self.map_story(story)
		# 		self.object['@levels']['elements'].append(level)

		# prepare room boundaries
		boundaries = self.add_collection('Room Separation Lines', 'Revit Category')
		self.object['elements'].append(boundaries)
		self.collections['boundaries'] = len(self.object['elements'])-1

		# iterate
		for collection in self.object['elements']:
			category = collection.name.lower()
			if collection.name == 'Room Separation Lines': # rewrite & add more
				pass
			elif category in self.categories:
				mapper = getattr(self, 'map_' + category)
				for i in range(0, len(collection['elements'])):
					collection['elements'][i] = mapper(
						speckle_object = collection['elements'][i]
					)
			else:
				self.log.warning(f"Translation skipped for category: $y(\"{collection.name}\")")

	# TODO !
	def map_beam(self, speckle_object, **parameters):
		"""
		Remap beam schema.
		"""
		bos = BaseObjectSerializer()
		beam = bos.traverse_base(speckle_object)[1]

		justification = {
			0: {'jy': 0, 'jz': 0},	# left, top
			1: {'jy': 1, 'jz': 0},	# center, top
			2: {'jy': 3, 'jz': 0},	# right, top
			3: {'jy': 0, 'jz': 1},	# left, center
			4: {'jy': 1, 'jz': 1},	# center, center
			5: {'jy': 3, 'jz': 1},	# right, center
			6: {'jy': 0, 'jz': 3},	# left, bottom
			7: {'jy': 1, 'jz': 3},	# center, bottom
			8: {'jy': 3, 'jz': 3},	# right, bottom
		}

		if beam['segments']['Segment #1']['assemblySegmentData']['buildingMaterial']:
			material = beam['segments']['Segment #1']['assemblySegmentData']['buildingMaterial']
		else:
			material = beam['segments']['Segment #1']['assemblySegmentData']['profileAttrName']

		surface = ''
		if 'topMaterial' in beam['segments']['Segment #1']:
			surface = ' ' + str(beam['segments']['Segment #1']['topMaterial'])

		general = self.get_general_parameters(beam)
		width = general.get('Cross Section Width at Bottom Start (cut')
		height = general.get('Cross Section Height at Bottom Start (cut')
		typo = f'{material} {width}x{height}{surface}'

		overrides = {
			'type': typo,
			'parameters': {
				'Y_JUSTIFICATION': {
					'value': justification[beam['anchorPoint']]['jy']
				},
				'Z_JUSTIFICATION': {
					'value': justification[beam['anchorPoint']]['jz']
				},
				'Y_OFFSET_VALUE': {
					'value': beam['offset']
				}
			}
		}
		beam = self.override_schema(beam, self.schema['revit']['beam'], overrides)

		return bos.recompose_base(beam)

	# TODO !
	def map_column(self, speckle_object, **parameters):
		"""
		Remap column schema.
		"""
		bos = BaseObjectSerializer()
		column = bos.traverse_base(speckle_object)[1]

		width = round(column['segments']['Segment #1']['assemblySegmentData']['nominalWidth']*1000)/1000
		height = round(column['segments']['Segment #1']['assemblySegmentData']['nominalHeight']*1000)/1000

		if not column.get('topLevel'):
			top_level = self.get_top_link(column, traverse=True)

		if not top_level:
			top_level = column['level']
			top_offset = column['bottomOffset'] + column['height']
		else:
			top_offset = column['topOffset']

		typo = "Col"
		if column['segments']['Segment #1']['assemblySegmentData']['modelElemStructureType'] == 'Complex Profile':
			typo = column['segments']['Segment #1']['assemblySegmentData']['profileAttrName'] + ' ' + str(height) + 'x' + str(width)
		else:
			typo = column['segments']['Segment #1']['assemblySegmentData']['buildingMaterial'] + ' ' + str(height) + 'x' + str(width)

		overrides = {
			'type': typo,
			'topLevel': top_level,
			'rotation': column['slantDirectionAngle'],
			'baseOffset': column['bottomOffset'],
			'topOffset': top_offset,
		}
		column = self.override_schema(column, self.schema['revit']['column'], overrides)

		return bos.recompose_base(column)

	# TODO !
	def map_curtainwall(self, speckle_object, **parameters):
		"""
		Remap curtain wall schema
		"""
		return speckle_object

	# TODO !
	def map_door(self, speckle_object, **parameters):
		"""
		Remap door schema
		"""
		return self.map_wido(speckle_object, **parameters)

	# TODO !
	def map_grid(self, speckle_object, **parameters):
		"""
		Remap structural grid system (axes)
		"""
		return speckle_object

	# TODO !
	def map_morph(self, speckle_object, **parameters):
		"""
		Remap morph schema
		"""
		return speckle_object

	# TODO !
	def map_object(self, speckle_object, **parameters):
		"""
		Remap object > generic / etc schema
		"""
		return speckle_object

	def map_opening(self, speckle_object, **parameters):
		"""
		Remap opening > shaft
		"""
		def map_opening_horizontal(speckle_object, **parameters):
			""" shaft openings in slabs, roofs, meshes? """
			opening = speckle_object
			general = self.get_general_parameters(opening)
			btm_offset = general.get('Bottom Elevation To Home Story', 0) if general else 0
			top_offset = general.get('Top Elevation To Home Story', 0) if general else 0
			altitude = top_offset - btm_offset

			opening.setdefault('bottomLevel', parameters['host_level'])
			opening.setdefault('topLevel', parameters['host_level'])

			overrides = {
				'height': altitude,
				'parameters': {
					'WALL_BASE_OFFSET': {
						'value': btm_offset,
					},
					'WALL_TOP_OFFSET': {
						'value': top_offset,
					}
				},
				'outline': {
					'segments': []
				}
			}
			shaft = self.override_schema(opening, self.schema['revit']['shaft_horizontal'], overrides)

			# flat list with x,y,z coordinates of each point
			# the last pair is redundant, as points to the first coordinates
			if 'value' in shaft['outline']:
				coords = shaft['outline']['value']
				for i in range(0, len(coords) // 3 - 2):
					sidx = i * 3
					eidx = (i + 1) * 3
					shaft['outline']['segments'].append(
						self.add_line(
							coords[sidx], coords[sidx+1], coords[sidx+2],
							coords[eidx], coords[eidx+1], coords[eidx+2],
							traverse=True))

				shaft['outline']['segments'].append(
					self.add_line(
						coords[-6], coords[-5],coords[-4],
						coords[0], coords[1], coords[2],
						traverse=True))

			return shaft

		def map_opening_vertical(speckle_object, **parameters):
			""" shaft openings in walls
				seems speckle translates opening in walls by itself
			"""
			return speckle_object

		if parameters['host'] == 'slab' or parameters['host'] == 'roof':
			return map_opening_horizontal(speckle_object, **parameters)
		elif parameters['host'] == 'wall':
			return map_opening_vertical(speckle_object, **parameters)

	# TODO !
	def map_railing(self, speckle_object, **parameters):
		"""
		Remap railing schema
		"""
		return speckle_object

	def map_roof(self, speckle_object, **parameters):
		"""
		Remap roof schema
		"""
		bos = BaseObjectSerializer()
		roof = bos.traverse_base(speckle_object)[1]

		general = self.get_general_parameters(roof)
		btm_offset = general.get('Bottom Elevation To Home Story', 0)
		body = self.get_material_body(roof)

		overrides = {
			'type': body,
			'TopElevationToHomeStory': btm_offset,
			'parameters': {
				'ROOF_LEVEL_OFFSET_PARAM': {
					'value': btm_offset
				}
			}
		}

		# note: there is an issue with curved slabs/roofs,
		# unit convertion doesn't work for some reason, so we have to redefine this segment
		for i in range(0, len(roof['outline']['segments'])-1):
			if 'plane' in roof['outline']['segments'][i]:
				segment = roof['outline']['segments'][i]
				# redefine plane & coordinates
				planeObj = Plane.from_list([0,0,0,	0,0,1,	1,0,0,	0,1,0, 3])
				plane = BaseObjectSerializer().traverse_base(planeObj)[1]
				start = self.add_point(
					segment['startPoint']['x']*1000,
					segment['startPoint']['y']*1000,
					segment['startPoint']['z']*1000,
					units='mm',
					traverse=True)
				mid = self.add_point(
					segment['midPoint']['x']*1000,
					segment['midPoint']['y']*1000,
					segment['midPoint']['z']*1000,
					units='mm',
					traverse=True)
				end = self.add_point(
					segment['endPoint']['x']*1000,
					segment['endPoint']['y']*1000,
					segment['endPoint']['z']*1000,
					units='mm',
					traverse=True)

				overrides_segment = {
					'plane': plane,
					'startPoint': start,
					'midPoint': mid,
					'endPoint': end,
					'angleRadians': segment['angleRadians']
				}
				roof['outline']['segments'][i] = self.override_schema(segment, self.schema['revit']['floor_segment_curved'], overrides_segment)

		roof = self.override_schema(roof, self.schema['revit']['roof'], overrides)

		return bos.recompose_base(roof)

	def map_slab(self, speckle_object, **parameters):
		"""
		Remap slab > floor schema.
		"""
		bos = BaseObjectSerializer()
		floor = bos.traverse_base(speckle_object)[1]

		general = self.get_general_parameters(floor)
		top_offset = general.get('Top Elevation To Home Story', 0) if general else 0  # revit uses top elevation
		body = self.get_material_body(floor)

		overrides = {
			'type': body,
			'TopElevationToHomeStory': top_offset,
			'parameters': {
				'FLOOR_HEIGHTABOVELEVEL_PARAM': {
					'value': top_offset
				}
			}
		}

		# note: there is an issue with curved slabs,
		# unit convertion doesn't work for some reason, so we have to redefine this segment
		for i in range(0, len(floor['outline']['segments'])-1):
			if 'plane' in floor['outline']['segments'][i]:
				segment = floor['outline']['segments'][i]
				# redefine plane & coordinates
				planeObj = Plane.from_list([0,0,0,	0,0,1,	1,0,0,	0,1,0, 3])
				plane = BaseObjectSerializer().traverse_base(planeObj)[1]
				start = self.add_point(
					segment['startPoint']['x']*1000,
					segment['startPoint']['y']*1000,
					segment['startPoint']['z']*1000,
					units='mm',
					traverse=True)
				mid = self.add_point(
					segment['midPoint']['x']*1000,
					segment['midPoint']['y']*1000,
					segment['midPoint']['z']*1000,
					units='mm',
					traverse=True)
				end = self.add_point(
					segment['endPoint']['x']*1000,
					segment['endPoint']['y']*1000,
					segment['endPoint']['z']*1000,
					units='mm',
					traverse=True)

				overrides_segment = {
					'plane': plane,
					'startPoint': start,
					'midPoint': mid,
					'endPoint': end,
					'angleRadians': segment['angleRadians']
				}
				floor['outline']['segments'][i] = self.override_schema(segment, self.schema['revit']['floor_segment_curved'], overrides_segment)

		floor = self.override_schema(floor, self.schema['revit']['floor'], overrides)

		# process sub elements
		if floor.get('elements', None):
			for e in range (0, len(floor['elements'])):
				element = floor['elements'][e]
				element_type = element['elementType'].lower()
				if element_type in self.categories:
					shaft = self.map_opening(
						speckle_object = floor['elements'][e],
						host = floor['elementType'].lower(),
						host_level = floor['level'],
						host_thickness = floor['thickness'],
						host_top_offset = top_offset
					)
					floor['elements'][e] = shaft

		return bos.recompose_base(floor)

	def map_story(self, story, **parameters):
		"""
		Remap story > level schema
		"""
		bos = BaseObjectSerializer()

		level = bos.read_json(json.dumps (self.schema['revit']['level'], indent = 4))
		level.id = story['id']
		level.name = story['name']
		# level.name = story.get('name', f"{story['index']} level on {story['elevation'] * 1000}")
		level.index = story['index']
		level.elevation = story['elevation']

		return level

	def map_wall(self, speckle_object, **parameters):
		"""
		Remap wall schema.

		Note: the global issue is in differences between maintaining baselines in Archicad an Revit.
		Revit uses center lines for internal positioning of entire wall, while Archicad operates
		according to the reference line location. So Speckle takes the "actual" baseline location according
		to Archicad, but not Revit. So we have to adjust the baseline location within the Speckle schema
		to "put" it into the "right" position from the Revit perspective.

		For straight walls it's just to offset x,y respectively.
		For curved walls we have to calculate midpoint according to saved start/stop point and then offset
		all the trio by the chord normal, according to the baseline position.
		"""
		bos = BaseObjectSerializer()
		wall = bos.traverse_base(speckle_object)[1]

		# retrieve top level linkage
		if not wall.get('topLevel'):
			top_level = self.get_top_link(wall, traverse=True)

		# ref line locations & ndir
		baseline = {
			'Center': (0, 1),		# Wall Centerline
			'Core Center': (1, 1),	# Core Centerline
			'Outside': (2, -1),		# Finish Face: Exterior
			'Inside': (3, -1),		# Finish Face: Interior
			'Core Outside': (4, 1),	# Core Face: Exterior
			'Core Inside': (5, -1)	# Core Face: Inside
		}

		# ref line coordinates
		sx = wall['baseLine']['start']['x']
		sy = wall['baseLine']['start']['y']
		sz = wall['baseLine']['start']['z']
		ex = wall['baseLine']['end']['x']
		ey = wall['baseLine']['end']['y']

		fix = wall['thickness'] / 2
		out = wall['offsetFromOutside'] if wall['offsetFromOutside'] else 0

		overrides = {
			'type': str(wall['structure']) + ' ' + str(wall['thickness']),
			'topLevel': top_level,
			'topOffset': wall['topOffset'],
			'parameters': {
				'WALL_KEY_REF_PARAM': {
					'value': baseline[wall['referenceLineLocation']][0]
				}
			}
		}

		# straight walls
		if not wall['arcAngle']:

			flip = -1 if wall['flipped'] == True else 1
			direction = self.get_vector_direction({'start': {'x': sx, 'y': sy }, 'end': {'x': ex, 'y': ey}})
			off_x = (out - fix) * direction['y'] * flip * -1
			off_y = (out - fix) * direction['x'] * flip

			wall_schema = self.schema['revit']['wall']
			wall_schema['baseLine'] = self.schema['revit']['wall_base']
			overrides['baseLine'] = {
				'start': {'x': sx + off_x, 'y': sy + off_y},
				'end': {'x': ex + off_x, 'y': ey  + off_y}
			}
			wall = self.override_schema(wall, wall_schema, overrides)

		# curved walls
		elif wall['arcAngle']:

			t = fix
			# chord midpoint
			dx = (sx + ex) / 2
			dy = (sy + ey) / 2

			# radius to origin circle
			chord = wall['baseLine']['length']
			radius = chord / (2 * math.sin(wall['arcAngle']/2))

			# angles
			slope = (ey - sy) / (ex - sx)
			slope_angle = math.atan(-1/slope) # bisector chord normale
			start_angle = (math.pi/2-wall['arcAngle']/2) - (math.pi/2-slope_angle)
			end_angle = math.pi - (math.pi/2-wall['arcAngle']/2) - (math.pi/2-slope_angle)

			# chord midpoint
			hypo = math.sqrt(radius**2 - (chord/2)**2)

			# direction vectors
			mvx = -int(math.copysign(1, dx-sx)) * int(math.copysign(1, slope_angle))	# mid
			svx =  int(math.copysign(1, dx-sx)) * int(math.copysign(1, slope_angle))	# start
			evx =  int(math.copysign(1, dx-sx)) * int(math.copysign(1, slope_angle))	# end
			
			# midpoint
			mx = dx + (radius - hypo) * math.cos(slope_angle) * mvx
			my = dy + (radius - hypo) * math.sin(slope_angle) * mvx

			# updated coordinates
			bdir = baseline[wall['referenceLineLocation']][1]
			mdx = mx + (t * math.cos(slope_angle) * -mvx * bdir)
			mdy = my + (t * math.sin(slope_angle) * -mvx * bdir)
			sdx = sx + (t * math.cos(start_angle) * svx * bdir)
			sdy = sy + (t * math.sin(start_angle) * svx * bdir)
			edx = ex + (t * math.cos(end_angle) * evx * bdir)
			edy = ey + (t * math.sin(end_angle) * evx * bdir)

			# redefine plane & coordinates
			planeObj = Plane.from_list([0,0,0,	0,0,1,	1,0,0,	0,1,0, 3])
			plane = BaseObjectSerializer().traverse_base(planeObj)[1]
			start = self.add_point(sdx, sdy, sz, traverse=True)
			mid = self.add_point(mdx, mdy, sz, traverse=True)
			end = self.add_point(edx, edy, sz, traverse=True)

			overrides['baseLine'] = {
				'plane': plane,
				'startPoint': start,
				'midPoint': mid,
				'endPoint': end,
				'angleRadians': wall['arcAngle']
			}

			wall_schema = self.schema['revit']['wall']
			wall_schema['baseLine'] = self.schema['revit']['wall_base_curved']
			wall = self.override_schema(wall, wall_schema, overrides)

		# map sub elements
		if wall.get('elements'):
			for e in range (0, len(wall['elements'])):
				element = wall['elements'][e]
				element_type = element['elementType'].lower()
				if element_type in self.categories:
					sub_mapper = getattr(self, 'map_' + element_type)
					sub = sub_mapper(
						speckle_object = wall['elements'][e],
						host = wall['elementType'].lower(),
						points = {'sx': sx, 'sy': sy, 'sz': sz, 'dx': direction['x'], 'dy': direction['y']}
					)
					sub['level'] = wall['level']
					wall['elements'][e] = sub
				else:
					self.log.warning(f"Translation skipped for category: $y(\"{element['elementType']}\")")

		return bos.recompose_base(wall)

	# TODO !
	def map_wido(self, speckle_object, **parameters):
		"""
		Remap door and window schema.
		"""
		wido = speckle_object
		general = self.get_general_parameters(wido)
		points = parameters['points']

		wido_id = general.get('Element ID', '')
		typo = f"{wido['libraryPart']} {wido['width']}x{wido['height']} {str(wido_id)}"

		overrides = {
			'type': typo,
			'definition': {
				'type': typo,
			},
			# todo: replace by speckle matrix methods!
			'transform': {
				'matrix': [
					# displace by axes
					1, 0, 0, 	points['sx'] + wido['objLoc'] * points['dx'],
					0, 1, 0, 	points['sy'] + wido['objLoc'] * points['dy'],
					0, 0, 1,	points['sz'] + wido['lower'],
					# homogeneous 
					0, 0, 0,	1
				]
			}
		}
		wido = self.override_schema(wido, self.schema['revit'][wido['elementType'].lower()], overrides)

		return wido

	# TODO !
	def map_window(self, speckle_object, **parameters):
		"""
		Remap windows schema
		"""
		return self.map_wido(speckle_object, **parameters)

	# TODO !
	def map_zone(self, speckle_object, **parameters):
		"""
		Remap zone > room schema.
		"""
		bos = BaseObjectSerializer()
		zone = bos.traverse_base(speckle_object)[1]

		properties = self.get_element_properties(zone)
		general = properties.get('General Parameters', {})
		group = properties.get('ZONESUM', {})

		area = general.get('Area', None)
		category = group.get('spk_prop_category', 'n/a')
		typo = group.get('spk_prop_type', None)
		function = group.get('spk_prop_func', None)
		number = group.get('spk_prop_num', None)
		gid = group.get('spk_prop_gid', None)

		for segment in zone['outline']['segments']:
			obs = BaseObjectSerializer()

			boundary = obs.traverse_base(Base())[1]
			boundary = {}
			boundary['level'] = zone['level']
			boundary['units'] = 'm'
			boundary['baseCurve'] = segment
			boundary['speckle_type'] = 'Objects.BuiltElements.Revit.Curve.RoomBoundaryLine'
			boundaryObj = obs.recompose_base(boundary)

			if self.object['elements'][self.collections['boundaries']]:
				self.object['elements'][self.collections['boundaries']]['elements'].append(boundaryObj)

		overrides = {
			'type': 'Room',
			'number': number,
			'parameters': {
				'ROOM_OCCUPANCY': {
					'value': category
				},
				'ROOM_DEPARTMENT': {
					'value': function
				}
			}
		}
		room = self.override_schema(zone, self.schema['revit']['room'], overrides)

		# todo: fix this method
		room['parameters']['4ff65744-b44a-40a8-a428-d9b649e4173b'] = {
			'name': 'MRT_A_RoomFixedArea',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '4ff65744-b44a-40a8-a428-d9b649e4173b',
			'applicationUnit': 'autodesk.unit.unit:squareMeters-1.0.1',
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': 'm²',
			'value': area
		}

		room['parameters']['2aaea987-7ae4-4484-8062-fbd77fc0bfbd'] = {
			'name': 'MRT_A_ApartmentType',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '2aaea987-7ae4-4484-8062-fbd77fc0bfbd',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': typo
		}

		room['parameters']['1f06fc4b-03e4-4ea2-917e-cf475cc0ea73'] = {
			'name': 'MRT_A_ApartmentID',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '1f06fc4b-03e4-4ea2-917e-cf475cc0ea73',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': gid
		}

		room['parameters']['75894bf8-8997-40ee-9130-d3dd46b1e109'] = {
			'name': 'MRT_A_RoomMod',
			'speckle_type': 'Objects.BuiltElements.Revit.Parameter',
			'applicationId': None,
			'applicationInternalName': '75894bf8-8997-40ee-9130-d3dd46b1e109',
			'applicationUnit': None,
			'applicationUnitType': None,
			'isReadOnly': False,
			'isShared': True,
			'isTypeParameter': False,
			'units': None,
			'value': 1
		}

		return bos.recompose_base(room)
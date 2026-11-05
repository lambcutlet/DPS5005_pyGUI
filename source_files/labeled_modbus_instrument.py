import minimalmodbus, serial
import time
import datetime
import tomllib

class LMInstrumentProperties:
	def __init__(self, filename):
		with open(filename, "rb") as f:
			config = tomllib.load(f)

		self.model = config["Model"]
		self.encoding = config["Encoding"]
		self.decimals = config["Decimals"]
		self.other = config["Other"]

		self.reg = config["Registers"]
		self.reg_name = {}
		for key, value in self.reg.items():
			try:
				self.reg_name[value] = key
			except:
				for v in value:
					self.reg_name[v] = key

		self.limits = config["Limits"]
		for key, value in self.limits.items():
			if (len(value) != 2):
				raise Exception(f"Error in {filename}: Limits need to consist of a min and max value (e.g.: vset = [0.0, 6.5]). Found {self.limits[key]} for key {key}")

class LabeledModbusInstrument:
	def __init__(self, instrument_properties, port, addr, baud_rate, timeout = 0.5, byte_size = 8):
		self.instrument = minimalmodbus.Instrument(
			serial.Serial(port, baud_rate, byte_size, serial.PARITY_NONE, 1,  timeout),
			addr,
			minimalmodbus.MODE_RTU
		)
		time.sleep(0.016) # ensure silent interval before any message is sent
		# see https://minimalmodbus.readthedocs.io/en/stable/serialcommunication.html?highlight=silent
		# temporary solution until https://github.com/pyhys/minimalmodbus/issues/141 is resolved
		# even with the proposed solution, this delay increases the success rate of the first message from 82% to 98% for the XY-SK120

		self.p = instrument_properties

		self.preset = None
		self._generate_keys_in_readable_groups()
	
	def read_addresses(self, addresses):
		# TODO: avoid too big blocks and forbidden addresses
		_min = min(addresses)
		count = max(addresses) - _min +1
		values = self.instrument.read_registers(_min, count)
		return [values[addr - _min] for addr in addresses]

	def decode_words(self, words, key):
		value = None
		if len(words) > 1:
			match key:
				case key if (key in self.p.decimals) or ((len(key) > 7) and(key[:7] == "preset_") and (key[7:] in self.p.decimals)):
					value = 0
					for i, word in enumerate(words):
						value += word<<(16*i)
				case "time":
					value = datetime.timedelta(hours = words[2], minutes = words[1], seconds = words[0])
				#case _:
				#	raise NotImplementedError(f"Unclear how to decode the words {words} for the key '{key}'. Maybe you need to adjust the device config (decimals).")
		else:
			value = words[0]

		match key:
			case "version":
				value = str(value)
				for i in range(self.p.decimals["version"]):
					n = i*2+1
					value = value[:-n] + '.' + value[-n:]	# version
			case key if key in self.p.decimals:
				value = value/float(10**self.p.decimals[key])
			case key if (len(key) > 7) and(key[:7] == "preset_") and (key[7:] in self.p.decimals): # use the decimals places defined for <name> on preset_<name>
				_key = key[7:]
				value = value/float(10**self.p.decimals[_key])
			case key if key in self.p.encoding:
				value = self.p.encoding[key][value]
			case "model":
				if int(value) in self.p.model['numbers']:
					value = self.p.model['name']
		return value

	def encode_value(self, key, value):
		match key:
			case "version":
				raise NotImplementedError("encode "+key);
			case key if key in self.p.decimals:
				value = int(value*10**self.p.decimals[key])
			case key if (len(key) > 7) and(key[:7] == "preset_") and (key[7:] in self.p.decimals): # use the decimals places defined for <name> on preset_<name>
				_key = key[7:]
				value = int(value*10**self.p.decimals[_key])
			case key if key in self.p.encoding:
				raise NotImplementedError("encode " + key)
			case "model":
				raise NotImplementedError("encode " + key)

		words = []
		#TODO: implement multi-word variables
		if isinstance(self.p.reg[key], list):
			raise NotImplementedError("setting multi-word parameters is not supported yet")
		else:
			words = [int(value)]

		return words

	def get_addresses(self, key, reevaluate_preset = True):
		part_of_settable_preset = (len(key) > 7) and (key[:7] == "preset_") and ("preset" in self.p.reg)
		if part_of_settable_preset and ((self.preset == None) or reevaluate_preset):
			preset_addr = self.p.reg["preset"]
			self.preset = self.instrument.read_register(preset_addr, 0)
			#print('Additional read for preset')

		addresses = self.p.reg[key]
		if isinstance(addresses, int):
			addresses = [addresses]

		if part_of_settable_preset:
			addresses = [address + self.preset*self.p.other['preset_offset'] for address in addresses]
		return addresses

	def read_value(self, key):
		addresses = self.get_addresses(key)
		words = self.read_addresses(addresses)

		value = self.decode_words(words, key)

		return value
	
	def read_values(self, keys, reevaluate_preset = True):
		addresses = []
		indices = []
		n = 0
		if reevaluate_preset:
			self.preset = None
		for i, key in enumerate(keys):
			key_addresses = self.get_addresses(key, reevaluate_preset=False)
			addresses.extend(key_addresses)

			m = len(key_addresses)
			indices.append(list(range(n, n+m)))
			n+= m
		words = self.read_addresses(addresses)
		grouped_words = [[words[i] for i in ind] for ind in indices]
		values = [self.decode_words(g_words, keys[i]) for i, g_words in enumerate(grouped_words)]
		value_dict = {key: values[i] for i, key in enumerate(keys)}
		return value_dict

	def _generate_keys_in_readable_groups(self, avoid_duplicates = True):
		sorted_addrs = sorted(self.p.reg_name.keys())

		self.key_groups = []
		current_group = []
		for i, address in enumerate(sorted_addrs):
			if (i == 0) or (current_group[-1] +1 == address):
				current_group.append(address)
			else:
				current_group_keys = [self.p.reg_name[x] for x in current_group]
				self.key_groups.append(current_group_keys)
				current_group = [address]
		current_group_keys = [self.p.reg_name[x] for x in current_group]
		self.key_groups.append(current_group_keys)

		#remove duplicates
		self.key_groups = [list(dict.fromkeys(group)) for group in self.key_groups]

		return self.key_groups
	
	def check_limits(self, key, value):
		if not key in self.p.limits:
			raise Exception("Acceptable range is unknown (incomplete device configuration).")
		min, max = self.p.limits[key]
		if (value < min) or (value > max):
			raise Exception(f"Value {value} is outside the allowed range ({min} .. {max}).")

	def write_value(self, key, value):
		self.check_limits(key, value)

		words = self.encode_value(key, value)

		addresses = self.get_addresses(key)
		if len(addresses) == 1:
			self.instrument.write_register(addresses[0], words[0], 0)

	def close(self):
		self.instrument.serial.close()
import minimalmodbus, serial
import time
import datetime
import csv
import traceback
import numpy as np

try:
	import ConfigParser
except ImportError:
	import configparser as ConfigParser

''' 
import the system limit thresholds from the *.ini file.
having a separate file allows simple modification for other versions of DPS supplies.
these limits prevent the program from issuing silly values.
'''
class Import_limits:
	def __init__(self, filename):
		self.reg = {}
		self.reg_name = {}
		self.decimals = {}
		self.encoding = {}
		self.limits = {}
		self._read_file(filename)
		self._read_file(self.device_config)
		
	def _read_file(self, filename):
		Config = ConfigParser.ConfigParser()
		found_files = Config.read(filename)
		if len(found_files) == 0:
			print(f"Config file '{filename}' not found. Potential fix: start the program directly from the containing folder.")
			quit()

		for section in Config.sections():
			for key in Config.options(section):
				value = Config.get(section, key)
				match section:
					case "Registers":
						value = self._parse_int_or_list(value)
						self.reg[key] = value
						try:
							self.reg_name[value] = key
						except:
							for v in value:
								self.reg_name[v] = key
					case "Encoding":
						self.encoding[key] = self._parse_int_or_list(value)
					case "Decimals":
						self.decimals[key] = int(value)
						exec("self.%s = %s" % ('decimals_'+key, value))
					case "Limits":
						self.limits[key] = self._parse_float_list(value)
						if len(self.limits[key]) != 2:
							raise Exception(f"Limits need to consist of a min and max value (e.g.: vset: 0.0, 6.5). Found values {self.limits[key]} for key {key}")
					case "SectionOne" | "SectionTwo" | "SectionThree":
						exec("self.%s = %s" % (key, value))
					case _:
						pass
	def _parse_int_or_list(self, value):
		try:
			return int(value)
		except:
			str_list = [x.strip() for x in value.split(',')]
			try:
				int_list = [int(x) for x in str_list]
				return int_list
			except:
				return str_list
	def _parse_float_list(self, value):
		str_list = [x.strip() for x in value.split(',')]
		float_list = [float(x) for x in str_list]
		return float_list


'''
# original inspiration for this came from here:
# DPS3005 MODBUS Example By Luke (www.ls-homeprojects.co.uk) 
#
# Requires minimalmodbus library from: https://github.com/pyhys/minimalmodbus
'''		
class Serial_modbus:
	def __init__(self, port, addr, baud_rate, byte_size, timeout = 0.5):
		self.instrument = minimalmodbus.Instrument(
			serial.Serial(port, baud_rate, byte_size, serial.PARITY_NONE, 1,  timeout),
			addr,
			minimalmodbus.MODE_RTU
		)

		time.sleep(0.016) # ensure silent interval before any message is sent
		# see https://minimalmodbus.readthedocs.io/en/stable/serialcommunication.html?highlight=silent
		# temporary solution until https://github.com/pyhys/minimalmodbus/issues/141 is resolved
		# even with the proposed solution, this delay increases the success rate of the first message from 82% to 98% for the XY-SK120

	def close(self):
		self.instrument.serial.close()
		pass

	def read(self, reg_addr, decimal_places):
		return self.instrument.read_register(reg_addr, decimal_places)
		
	def read_block(self, reg_addr, size_of_block):
		return self.instrument.read_registers(reg_addr, size_of_block)

	def write(self, reg_addr, value, decimal_places):
		self.instrument.write_register(reg_addr, value, decimal_places) # register, value, No_of_decimal_places
	
	def write_block(self, reg_addr, value):
		self.instrument.write_registers(reg_addr, value)

class LabeledModbusInstrument:
	def __init__(self, device_properties, port, addr, baud_rate, timeout = 0.5, byte_size = 8):
		self.instrument = minimalmodbus.Instrument(
			serial.Serial(port, baud_rate, byte_size, serial.PARITY_NONE, 1,  timeout),
			addr,
			minimalmodbus.MODE_RTU
		)
		time.sleep(0.016) # ensure silent interval before any message is sent
		# see https://minimalmodbus.readthedocs.io/en/stable/serialcommunication.html?highlight=silent
		# temporary solution until https://github.com/pyhys/minimalmodbus/issues/141 is resolved
		# even with the proposed solution, this delay increases the success rate of the first message from 82% to 98% for the XY-SK120

		self.dev = device_properties

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
				case key if (key in self.dev.decimals) or ((len(key) > 7) and(key[:7] == "preset_") and (key[7:] in self.dev.decimals)):
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
				for i in range(self.dev.decimals["version"]):
					n = i*2+1
					value = value[:-n] + '.' + value[-n:]	# version
			case key if key in limits.decimals:
				value = value/float(10**self.dev.decimals[key])
			case key if (len(key) > 7) and(key[:7] == "preset_") and (key[7:] in limits.decimals): # use the decimals places defined for <name> on preset_<name>
				_key = key[7:]
				value = value/float(10**self.dev.decimals[_key])
			case key if key in limits.encoding:
				value = limits.encoding[key][value]
			case "model":
				if int(value) in limits.model_numbers:
					value = limits.model_name
		return value

	
	def encode_value(self, key, value):
		match key:
			case "version":
				raise NotImplementedError("encode "+key);
			case key if key in limits.decimals:
				value = int(value*10**self.dev.decimals[key])
			case key if (len(key) > 7) and(key[:7] == "preset_") and (key[7:] in limits.decimals): # use the decimals places defined for <name> on preset_<name>
				_key = key[7:]
				value = int(value*10**self.dev.decimals[_key])
			case key if key in limits.encoding:
				raise NotImplementedError("encode " + key)
			case "model":
				raise NotImplementedError("encode " + key)

		words = []
		#TODO: implement multi-word variables
		if isinstance(self.dev.reg[key], list):
			raise NotImplementedError("setting multi-word parameters is not supported yet")
		else:
			words = [int(value)]

		return words

	def get_addresses(self, key, reevaluate_preset = True):
		part_of_settable_preset = (len(key) > 7) and (key[:7] == "preset_") and ("preset" in self.dev.reg)
		if part_of_settable_preset and ((self.preset == None) or reevaluate_preset):
			preset_addr = self.dev.reg["preset"]
			self.preset = self.instrument.read_register(preset_addr, 0)

		addresses = self.dev.reg[key]
		if isinstance(addresses, int):
			addresses = [addresses]

		if part_of_settable_preset:
			addresses = [address + self.preset*self.dev.preset_offset for address in addresses]
		return addresses

	def read_value(self, key):
		addresses = self.get_addresses(key)
		words = self.read_addresses(addresses)

		value = self.decode_words(words, key)

		return value
	
	def read_values(self, keys):
		addresses = []
		indices = []
		n = 0
		for i, key in enumerate(keys):
			key_addresses = self.get_addresses(key)
			addresses.extend(key_addresses)

			m = len(key_addresses)
			indices.append(n + np.arange(m))
			n+= m
		words = self.read_addresses(addresses)
		grouped_words = [[words[i] for i in ind] for ind in indices]
		values = [self.decode_words(g_words, keys[i]) for i, g_words in enumerate(grouped_words)]
		value_dict = {key: values[i] for i, key in enumerate(keys)}
		return value_dict

	def _generate_keys_in_readable_groups(self, avoid_duplicates = True):
		sorted_addrs = sorted(self.dev.reg_name.keys())

		self.key_groups = []
		current_group = []
		for i, address in enumerate(sorted_addrs):
			if (i == 0) or (current_group[-1] +1 == address):
				current_group.append(address)
			else:
				current_group_keys = [self.dev.reg_name[x] for x in current_group]
				self.key_groups.append(current_group_keys)
				current_group = [address]
		current_group_keys = [self.dev.reg_name[x] for x in current_group]
		self.key_groups.append(current_group_keys)

		#remove duplicates
		self.key_groups = [list(dict.fromkeys(group)) for group in self.key_groups]

		return self.key_groups
	
	def check_limits(self, key, value):
		if not key in self.dev.limits:
			raise Exception("Acceptable range is unknown (incomplete device configuration).")
		min, max = self.dev.limits[key]
		if (value < min) or (value > max):
			raise Exception(f"Value {value} is outside the allowed range ({min} .. {max}).")

	def write_value(self, key, value):
		self.check_limits(key, value)

		words = self.encode_value(key, value)

		addresses = self.get_addresses(key)
		if len(addresses) == 1:
			self.instrument.write_register(addresses[0], words[0], 0)


class Dps5005:
  #--- new ---
	def __init__(self, ser, limits):
		self.serial_data = ser
		self.limits = limits
		
	def voltage_set(self, RWaction='r', value=0.0):	# R/W
		return self.function(limits.reg['vset'], self.limits.decimals_vset, RWaction, value, self.limits.voltage_set_max, self.limits.voltage_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value 

	def current_set(self, RWaction='r', value=0.0):	# R/W
		return self.function(limits.reg['iset'], self.limits.decimals_iset, RWaction, value, self.limits.current_set_max, self.limits.current_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value 

	def voltage(self):	# R
		return self.function(limits.reg['v'], self.limits.decimals_v) 

	def current(self):	# R
		return self.function(limits.reg['i'], self.limits.decimals_i)

	def power(self):	# R
		return self.function(limits.reg['power'], self.limits.decimals_power)

	def voltage_in(self):	# R
		return self.function(limits.reg['vin'], self.limits.decimals_vin)

	def lock(self, RWaction='r', value=0):	# R/W
		return self.function(limits.reg['lock'], 0, RWaction, value, self.limits.lock_set_max, self.limits.lock_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def protect(self):	# R
		return self.function(limits.reg['protect'], 0)

	def cv_cc(self):	# R
		return self.function(limits.reg['cv_cc'], 0)

	def onoff(self, RWaction='r', value=0):	# R/W
		return self.function(limits.reg['on'], 0, RWaction, value, self.limits.onoff_set_max, self.limits.onoff_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value
		
	def b_led(self, RWaction='r', value=0):	# R/W
		return self.function(limits.reg['backlight'], 0, RWaction, value, self.limits.b_led_set_max, self.limits.b_led_set_min) # reg_addr, decimal_places, RWaction, value, max_value, min_value

	def model(self):	# R
		return self.function(limits.reg['model'], 0)

	def version(self):	# R
		version = str(self.function(limits.reg['version'], 0))
		for i in range(self.limits.decimals_version):
			n = i*2+1
			version = version[:-n] + '.' + version[-n:]	# version
		return version

	def read_all(self, reg_addr = 0x00, block_size = 30):	# Read data as a block, much faster than individual reads
		data_raw = self.functions(reg_addr, num_of_addr=block_size, RWaction = 'r') # reg_addr, number of bytes, RWaction, value
		
		#TODO remove data variable (needs refactoring of dependencies)
		data = data_raw.copy()
		try:
			data[0] = data_raw[0] / float(10**self.limits.decimals_vset)	# voltage_set
			data[1] = data_raw[1] / float(10**self.limits.decimals_iset)	# current_set
			data[2] = data_raw[2] / float(10**self.limits.decimals_v)		# voltage
			data[3] = data_raw[3] / float(10**self.limits.decimals_i)		# current
			data[4] = data_raw[4] / float(10**self.limits.decimals_power)	# power
			data[5] = data_raw[5] / float(10**self.limits.decimals_vin)	 	# voltage_in
			data[13] = data_raw[13] / float(10**self.limits.decimals_temp_internal)	# temperature internal
			data[8] = data_raw[8] / float(10**self.limits.decimals_energy)	# energy

			data[19] = "°F" if data_raw[19] else "°C"

			data[23] = str(data_raw[23])
			for i in range(self.limits.decimals_version):
				n = i*2+1
				data[23] = data[23][:-n] + '.' + data[23][-n:]	# version
		except Exception:
			print(traceback.format_exc())

		data_dict = {}
		for key in limits.reg:
			index = limits.reg.get(key)
			value = None
			if isinstance(index, list):
				multi_word = True
				words = []
				try:
					for i in index:
						addr = i-reg_addr
						assert addr >= 0
						words.append(data_raw[addr])
				except IndexError, AssertionError:
					continue
				match key:
					case key if key in limits.decimals:
						value = 0
						for i, word in enumerate(words):
							value += word<<(16*i)
						value = value/float(10**self.limits.decimals[key])
					case "time":
						value = datetime.timedelta(hours = words[2], minutes = words[1], seconds = words[0])

						
			elif isinstance(index, int):
				try:
					addr = index-reg_addr
					assert addr >= 0
					value = data_raw[addr]
				except IndexError, AssertionError:
					continue
				match key:
					case "version":
						value = str(value)
						for i in range(self.limits.decimals_version):
							n = i*2+1
							value = value[:-n] + '.' + value[-n:]	# version
					case key if key in limits.decimals:
						value = value/float(10**self.limits.decimals[key])
					case key if (len(key) > 7) and(key[:7] == "preset_") and (key[7:] in limits.decimals):
						_key = key[7:]
						value = value/float(10**self.limits.decimals[_key])
					case key if key in limits.encoding:
						value = limits.encoding[key][value]
					case "temp_unit":
						"°F" if value else "°C"
					case "model":
						if int(value) in limits.model_numbers:
							value = limits.model_name
			data_dict[key] = value
			#print(reg_addr, index, key, data_dict[key])

		for i, value in enumerate(data_raw):
			key = limits.reg_name.get(i)
			
		return data, data_raw, data_dict
	
	

	def write_voltage_current(self, RWaction='r', value=0):	# write voltage & current as a block
		reg_addr = 0x00 
		# added safety limits - any excursion results in zero
		if value[0] > self.limits.voltage_set_max or value[0] < self.limits.voltage_set_min: 
			value[0] = 0
		value[0] = int(value[0] * float(10**self.limits.decimals_v))	#100.0	# voltage
		if value[1] > self.limits.current_set_max or value[1] < self.limits.current_set_min: 
			value[1] = 0
		value[1] = int(value[1] * float(10**self.limits.decimals_i))	#1000.0	# current
		
		self.functions(reg_addr, 0, 'w', value)
		
	def write_all(self, reg_addr=0, value=0):	# write block
		self.functions(reg_addr, 0, 'w', value)
		
  #---
	


	def function(self, reg_addr=0, decimal_places=0, RWaction='r', value=0.0, max_value=0, min_value=0):
		a = False
		if value > max_value or value < min_value: 
			value = 0.0
		if RWaction != 'w':
			try:
				a = self.serial_data.read(reg_addr, decimal_places)
			except IOError:
				print("Failed to read from instrument")
		else:
			try:
				self.serial_data.write(reg_addr, value, decimal_places) # register, value, No_of_decimal_places
			except IOError:
				print("Failed to write to instrument")
		return(a)
	
	def functions(self, reg_addr=0, num_of_addr=0, RWaction='r', value=0):
		a = False
		if RWaction != 'w':
			try:
				a = self.serial_data.read_block(reg_addr, num_of_addr)
			except IOError:
				print("Failed to read block from instrument")
		else:
			try:
				self.serial_data.write_block(reg_addr, value)
			except IOError:
				print("Failed to write block to instrument")
		return(a)
	
	def delay(self, value):
		global time_old
		value = float(value)
		if value == 0.0:
			time_old = time.time()

		while True:
			time_interval = time.time() - time_old
			if time_interval >= value:
				time_old = time.time()
				break
			time.sleep(0.01)

	def check_model(self, verbose = True):
		model = self.model()
		model_hex = hex(model)[2:]
		expected_model_strings = [str(number) for number in self.limits.model_numbers]
		match = model_hex in expected_model_strings
		if verbose:
			if match:
				print(f"Model number {model_hex} matches with config file for Model {self.limits.model_name}.")
			else:
				print(f"Model number {model_hex} is not in the list of expected numbers {self.limits.model_numbers} for the configured model {self.limits.model_name}. Please verify that your configuration is correct.")
		return match

	
	def action_csv_file(self, filename='sample.csv', value=0):
		try:
			with open(filename, 'r') as f:
				csvReader = csv.reader(f)#, delimiter=',')	# reads file
				next(csvReader, None)						# skips header
				data_list = list(csvReader)
				print(data_list)
			# initialise dps state
				self.voltage_set('w', float(0.0))			# set voltage to zero
				self.current_set('w', float(0.0))			# set current to zero
				self.onoff('w', 1)							# enable output
				total_time = 0
			# calculate test time
				for row in data_list:
					total_time += float(row[0])
				print("Test Time: %5.1fseconds" % (total_time))
			# perform test
				for row in data_list:
					value0 = float(row[0])
					value1 = float(row[1])
					value2 = float(row[2])
					print(" Step_time: %5.1fs, Voltage: %5.2fV, Current: %5.3fA" % (value0, value1, value2))
					self.voltage_set('w', value1)
					self.current_set('w', value2)
					self.delay(value0)
			self.onoff('w', 0)							# disable output
			print("Complete!")
			return
		except:
			print("Failed to load file.")

'''
This file can operate independently controlling the DPS via the commandline however the GUI is much simpler.
'''
if __name__ == '__main__':
	limits = Import_limits("config.ini")

	try:
		print("Serial port: "+limits.port_set)
		ser = Serial_modbus(limits.port_set, 1, 115200, 8)
	except Exception as e:
		print(f"Could not open the serial port '{limits.port_set}'.")
		print(e.args)
		quit()
	if False:
		dps = Dps5005(ser, limits)
		try:
			while True:
				command = input("Enter command: ")
				if command == "q":
					quit()
				elif command == "r":
					for reg_addr, block_size in [(0, 40), (0x50, 15), (0x60, 15), (0x70, 15)]:
						try:
							values, raw_values, value_dict = dps.read_all(reg_addr, block_size=block_size)
							print(    f"Address [hex] |  Raw  | Value |    Check | Meaning")
							for i, value in enumerate(values):
								addr = reg_addr+i
								meaning = limits.reg_name.get(addr) or ""
								try:
									sanity_check = value_dict[meaning] if meaning else "     "
								except KeyError:
									sanity_check = 'incomplete'
								try:
									sanity_check_str = f"{sanity_check:8}"
								except Exception:
									sanity_check_str = f"{sanity_check}"
								print(f"      {addr:02} [{addr:02x}] | {raw_values[i]:5} | {value:5} | {sanity_check_str} | {meaning}")
						except AttributeError:
							print(traceback.format_exc())
				elif command == "dump": # test accessability of the registers, try to read all values
					reg_addr = 0
					block_size=1
					valid_addresses = []
					Invalid_addresses = []
					address_overview = ''
					address_overview_2 = ''
					while reg_addr <= 2**8-block_size:
						try:
							print(reg_addr)
							values, raw_values, value_dict = dps.read_all(reg_addr, block_size=block_size)
							for i, value in enumerate(values):
								addr = reg_addr+i
								valid_addresses.append(reg_addr+i) 
							address_overview += (''.join([("." if x else "0") for x in raw_values]))
							address_overview_2 += (''.join([f"{x:6} " for x in raw_values]))
						except AttributeError:
							Invalid_addresses.append(reg_addr) # for blocksizes > 1 this is not correct
							x = ("x"*block_size)
							address_overview += x
							_x = ("     _ "*block_size)
							address_overview_2 += _x
						if (reg_addr +block_size) %16 == 0:
							address_overview += "\n"
							address_overview_2 += "\n"
						reg_addr += block_size
					print(f"{valid_addresses=}")
					print(f"{Invalid_addresses=}")
					print("overview")
					print(address_overview)
					print(address_overview_2)
				elif command == "write":
					value = [23.47, 1.23]
					dps.write_voltage_current('w', value)
				elif command == "vset":
					value = input("Enter value: ")
					dps.voltage_set('w', float(value))
				elif command == "iset":
					value = input("Enter value: ")
					dps.current_set('w', float(value))
				elif command == "lock":
					value = input("Enter value: ")
					dps.lock('w', float(value))
				elif command == "on":
					dps.onoff('w', 1)
				elif command == "off":
					dps.onoff('w', 0)
				elif command == "m":	
					for i in dir(dps):
						print(i)
				elif command == "a":	
					dps.action_csv_file('dps-control-Book1.csv')
				else:
					pass

		except KeyboardInterrupt:  	# Ctrl+C pressed, so...
			print("close")
		except Exception as e:
			print('Error', e.args)
			print(traceback.format_exc())
			print()
			print("Trying to turn off the power supply due to the error.")
			dps.onoff('w', 0)
		finally:
			quit()
	else:
		instr = LabeledModbusInstrument(limits, limits.port_set, 1, 115200)
		try:
			while True:
				command = input("Enter command: ")
				match command:
					case "q":
						quit()
					case "r":
						for keys in instr.key_groups:
							values = instr.read_values(keys)
							for i, key in enumerate(keys):
								print(f"{key:>22}: {values[key]}")
							print(' --')
					case "w":
						key = input(' Enter the name of the variable: ')
						value = input(' Enter the value: ')
						value = float(value)
						instr.write_value(key, value)
					case _:
						print("Unknown command. Press Ctrl+C or enter q to quit.")

		except KeyboardInterrupt:  	# Ctrl+C pressed, so...
			print("close")
		except Exception as e:
			#print('Error', e.args)
			print(traceback.format_exc())
			print()
			print("Trying to turn off the power supply due to the error...")
			try:
				instr.write_value('on', 0)
				print("Turned off")
			except Exception:
				print("Failed to turn off")
		finally:
			quit()

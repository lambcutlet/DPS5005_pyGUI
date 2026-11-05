import minimalmodbus, serial
import time
import datetime
import csv
import traceback
import numpy as np

from labeled_modbus_instrument import LabeledModbusInstrument, LMInstrumentProperties

try:
	import ConfigParser
except ImportError:
	import configparser as ConfigParser

import tomllib

''' 
import the configuration from a *.ini config file.
'''
class Import_config(dict):
	def __init__(self, filename):
		self._read_config_file(filename)

	def _read_config_file(self, filename):
		Config = ConfigParser.ConfigParser()
		found_files = Config.read(filename)
		if len(found_files) == 0:
			print(f"Config file '{filename}' not found. Potential fix: start the program directly from the containing folder.")
			quit()

		for section in Config.sections():
			for key in Config.options(section):
				value = Config.get(section, key)
				match section:
					case "SectionOne" | "SectionTwo" | "SectionThree":
						exec("self.%s = %s" % (key, value))
					case _:
						pass

class ProgrammablePowerSupply:
  #--- new ---
	def __init__(self, labeledModbusInstrument):
		self.instr = labeledModbusInstrument

	def read_all(self):	# Read data as continuous blocks, much faster than individual reads
		result_dict = {}
		self.instr.preset = None
		for keys in self.instr.key_groups:
			block_dict = self.instr.read_values(keys, reevaluate_preset=False)
			if 'preset' in block_dict:
				self.instr.preset = block_dict['preset']
				#print('set preset from block')
			result_dict = result_dict | block_dict
		#print("pps.read_all -", result_dict)
		return result_dict

	def check_model(self, verbose = True):
		model = self.instr.read_value('model')
		model_is_a_match = (model == self.instr.p.model['name'])
		if verbose:
			if model_is_a_match:
				print(f"Model number matches with config file for Model {self.instr.p.model['name']}.")
			else:
				print(f"Model number {model} is not in the list of expected numbers {self.instr.p.model['numbers']} for the configured model {self.instr.p.model['name']}. Please verify that your configuration is correct.")
		return model_is_a_match

	def str_format_decimals(self, value_dict, min_width = 5):
		result = {}
		for key, value in value_dict.items():
			if (key in self.instr.p.decimals) and (not isinstance(value, str)):
				result[key] = f"{value_dict[key]:{min_width}.{self.instr.p.decimals[key]}f}"
		return result

'''
This file can operate independently controlling the DPS via the commandline however the GUI is much simpler.
'''
if __name__ == '__main__':
	limits = Import_config("config.ini")

	try:
		print("Serial port: "+limits.port_set)
		ser = Serial_modbus(limits.port_set, 1, 115200, 8)
	except Exception as e:
		print(f"Could not open the serial port '{limits.port_set}'.")
		print(e.args)
		quit()
	if False:
		dps = Dps5005(ser, self.limits)
		try:
			while True:
				command = input("Enter command: ")
				if command == "q":
					quit()
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
				elif command == "m":	
					for i in dir(dps):
						print(i)
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
		prop = LMInstrumentProperties(limits.device_config)
		instr = LabeledModbusInstrument(prop, limits.port_set, 1, 115200)
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

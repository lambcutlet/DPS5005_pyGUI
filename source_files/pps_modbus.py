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

	prop = LMInstrumentProperties(limits.device_config)
	try:
		print("Serial port: "+limits.port_set)
		modbus_addr = 1
		instr = LabeledModbusInstrument(prop, limits.port_set, modbus_addr, 115200)
	except Exception as e:
		print(f"Could not open the instrument on serial port '{limits.port_set}' at Modbus address {modbus_addr}.")
		print(e.args)
		quit()
	try:
		print('Available commands: r (read values), dump (memory dump, test all addresses), w (write value)')
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
				case "dump":
					data_raw = {}
					data = {}
					data_addr = {}
					illegal_address = []
					address_overview_small = 'row+0123456789abcdef (row+column = address)\n'
					address_overview_detail = ''
					print("reading addresses...")
					length = 256+16
					for addr in range(length):
						if addr %16 == 0:
							address_overview_small += f'{hex(int(addr))[2:]:>3}|'
						try:
							data_raw[addr] = instr.instrument.read_register(addr)
							#print(' read', addr, data_raw[addr])
							address_overview_small += '.'
							address_overview_detail += f"{data_raw[addr]:6} "
						except minimalmodbus.IllegalRequestError:
							data_raw[addr] = 'x'
							address_overview_small += 'x'
							address_overview_detail += '     _ '
							illegal_address.append(addr)
						if (addr +1) %16 == 0:
							address_overview_small += "\n"
							address_overview_detail += "\n"
							print(f" {addr+1}/{length}")
					for key, addrs in instr.p.reg.items():
						if isinstance(addrs, int):
							addrs = [addrs]
						all_values_present = True
						for addr in addrs:
							if data_raw.get(addr) in (None, 'x'):
								all_values_present = False
								break
						if not all_values_present:
							continue

						words = [data_raw[i] for i in addrs]
						value = instr.decode_words(words, key)
						data[key] = value
						for addr in addrs:
							data_addr[addr] = value
					
					print()
					print("Register Overview (16 per row, 'x' is invalid, '.' is valid)")
					print(address_overview_small)
					print()
					print("Illegal addresses:")
					print(illegal_address)
					print()
					print("Registers - detailed view ('_' is invalid)")
					print(address_overview_detail)
					print()

					print('Register labels and interpreted values (only the first presets is resolved here)')
					print('[addr|hex]    raw |            label |  value')
					print('---------------------------------------------')
					for i in range(length):
						label = instr.p.reg_name.get(i)
						if label == None:
							label=''
						try:
							interpreted_data = f"{data_addr.get(i):>6}"
						except:
							if data_addr.get(i) == None:
								interpreted_data = ''
							else:
								interpreted_data = str(data_addr.get(i))
						print(f"[{i:4}|{hex(i)[2:]:>3}] {data_raw[i]:>6} | {label:>16} | {interpreted_data}")
						
				case _:
					print("Unknown command. Press Ctrl+C or enter q to quit.")

	except KeyboardInterrupt:  	# Ctrl+C pressed, so...
		print("close")
	except Exception as e:
		#print('Error', e.args)
		print(traceback.format_exc())
		print()
	finally:
		quit()

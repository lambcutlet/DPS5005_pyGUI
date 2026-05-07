import sys
import glob
import os
from dps_modbus import Serial_modbus
from dps_modbus import Dps5005
from dps_modbus import Import_limits
import serial
import time
import csv
import datetime
import logging
import traceback

from PyQt5.QtCore import pyqtSlot, pyqtSignal, QRunnable, QThreadPool, QTimer, QThread, QCoreApplication, QObject, QMutex, Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QSlider, QAction, QFileDialog, QGraphicsView
from PyQt5.QtGui import QIcon, QFont
from PyQt5.uic import loadUi

# Configure logging
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

import pyqtgraph as pg
import numpy as np

class WorkerSignals(QObject):
	finished = pyqtSignal()
	error = pyqtSignal(tuple)
	result = pyqtSignal(object)
	progress = pyqtSignal(int)

class Worker(QRunnable):
	def __init__(self, fn, *args, **kwargs):
		super(Worker, self).__init__()
		# Store constructor arguments (re-used for processing)
		self.fn = fn
		self.args = args
		self.kwargs = kwargs
		self.signals = WorkerSignals()

		# Add the callback to our kwargs
		kwargs['progress_callback'] = self.signals.progress

	@pyqtSlot()
	def run(self):
		try:
			result = self.fn(*self.args, **self.kwargs)
		except Exception as e:
			self.signals.error.emit((type(e).__name__, e, traceback.format_exc()))
		else:
			self.signals.result.emit(result)  # Return the result of the processing
		finally:
			self.signals.finished.emit()  # Done


class dps_GUI(QMainWindow):
	def __init__(self):
		super(dps_GUI, self).__init__()
		self.limits = Import_limits("dps5005_limits.ini")
		pg.setConfigOption('background', self.limits.background_colour)
		
		loadUi('dps_GUI.ui', self)
		
		self.setWindowTitle('DPS5005_pyGUI')
		
		self.dps = None
		self.dps_mode = 0  # 0 PSU default, 1 nicad, 2 li-ion, 3 CSV, 
		
		self.mutex = QMutex()
		self.serialconnected = False
		self.slider_in_use = False
		self.CSV_file = ''
		self.CSV_list = []
		self.graph_X = []
		self.graph_Y1 = []
		self.graph_Y2 = []
		self.time_old = ""
		self.capacity_time_old = ""
		self.capacity = 0.0
		self.pushButton_on_start_time = 0
		self.v_peak = 0.0
		self.v_terminate = 0.0
		self.i_terminate = 0.0
		
	#--- fix font style & size, mainly for HighDpiScaling
		f = QFont("Liberation Sans", 10)
		self.setFont(f)
		
	#--- PlotWidget
		self.pg_plot_setup()
		
	#--- threading
		self.threadpool = QThreadPool()
	#   logger.info("Multithreading with maximum %d threads" % self.threadpool.maxThreadCount())
		
	#--- connect signals + keyboard shortcuts + status tips
		self.pushButton_save_plot.clicked.connect(self.pushButton_save_plot_clicked)
		self.pushButton_save_plot.setShortcut(Qt.CTRL | Qt.Key_S)                                        # 'Save Plot' - save file/plot *.csv
		self.pushButton_save_plot.setStatusTip('Save Plot - CTRL+S')
		
		self.pushButton_clear_plot.clicked.connect(self.pushButton_clear_plot_clicked)
		self.pushButton_clear_plot.setShortcut(Qt.CTRL | Qt.Key_L)                                        # 'Clear' - clear/new plot
		self.pushButton_clear_plot.setStatusTip('Clear Plot - CTRL+L')
		
		self.radioButton_lock.clicked.connect(self.radioButton_lock_clicked)
		self.radioButton_lock.setShortcut(Qt.CTRL | Qt.ALT | Qt.Key_L)                                # 'Lock' - toggle status
		self.radioButton_lock.setStatusTip('Toggle Lock - CTRL+ALT+L')
		
		self.pushButton_onoff.clicked.connect(self.pushButton_onoff_clicked)                # On / Off
		
		self.pushButton_set.clicked.connect(self.pushButton_set_clicked)                        # 'Set' - PSU
		self.pushButton_set_2.clicked.connect(self.pushButton_set_2_clicked)                # 'Set' - NiMH/NiCad
		self.pushButton_set_3.clicked.connect(self.pushButton_set_3_clicked)                # 'Set' - Li-Ion/Lipo
		
		self.pushButton_connect.clicked.connect(self.pushButton_connect_clicked)        # 'Connect'
		
		self.pushButton_CSV.clicked.connect(self.pushButton_CSV_clicked)                        # 'CSV run'
		self.pushButton_CSV_clear.clicked.connect(self.pushButton_CSV_clear_clicked)# 'CSV clear'
		self.pushButton_CSV_view.clicked.connect(self.pushButton_CSV_view_clicked)        # 'CSV view'
		
		self.horizontalSlider_brightness.sliderReleased.connect(self.horizontalSlider_brightness_sliderReleased)
		self.horizontalSlider_brightness.sliderMoved.connect(self.horizontalSlider_brightness_sliderMoved)
		
		self.actionOpen.triggered.connect(self.file_open)
		self.actionOpen.setShortcut(Qt.CTRL | Qt.Key_O)                                                                # File -> Open - open file *.csv
		self.actionOpen.setStatusTip('File Open - CTRL+O')
				
		self.actionQuit.triggered.connect(self.close)
		self.actionQuit.setShortcut(Qt.CTRL | Qt.Key_Q)                                                                # File -> Quit - quit application
		self.actionQuit.setStatusTip('Quit application - CTRL+Q')
		
	#--- do once on startup
		self.combobox_populate()

	#--- setup & run background task
		self.timer2 = QTimer()
		self.timer2.setInterval(10)
		self.timer2.timeout.connect(self.action_CSV)
		
		self.timer = QTimer()
		self.timer.setInterval(1000)
		self.timer.timeout.connect(self.loop_function)

	def closeEvent(self, event):    
		self.shutdown() # switch OFF output when application closes to prevent unmonitored charging
		event.accept()
		
	def shutdown(self):
		if self.pushButton_onoff.isChecked() == True:   
			self.label_onoff.setText('Output      :   OFF') # off
			self.pushButton_onoff.setChecked(False)
			self.pushButton_onoff_clicked()
			logger.info("System shutdown - output switched off")
			
	def pg_plot_setup(self): # right axis not connected to automatic scaling on the left ('A' icon on bottom LHD)
		self.p1 = self.graphicsView.plotItem
		self.p1.setClipToView(True)     

	# x axis    
		self.p1.setLabel('bottom', 'Time', units='s', color=self.limits.x_colour, **{'font-size':'10pt'})
		self.p1.getAxis('bottom').setPen(pg.mkPen(color=self.limits.x_colour, width=self.limits.x_pen_weight))

	# Y1 axis   
		self.p1.setLabel('left', 'Voltage', units='V', color=self.limits.y1_colour, **{'font-size':'10pt'})
		self.pen_Y1 = pg.mkPen(color=self.limits.y1_colour, width=self.limits.y1_pen_weight)
		self.p1.getAxis('left').setPen(self.pen_Y1)
	
	# setup viewbox for right hand axis
		self.p2 = pg.ViewBox()
		self.p1.showAxis('right')
		self.p1.scene().addItem(self.p2)
		self.p1.getAxis('right').linkToView(self.p2)
		self.p2.setXLink(self.p1)

	# Y2 axis
		self.p1.setLabel('right', 'Current', units="A", color=self.limits.y2_colour, **{'font-size':'10pt'})
		self.pen_Y2 = pg.mkPen(color=self.limits.y2_colour, width=self.limits.y2_pen_weight)
		self.p1.getAxis('right').setPen(self.pen_Y2)
		
	# scales ViewBox to scene
		self.p1.vb.sigResized.connect(self.updateViews)      

	def updateViews(self):
		self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
		self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)

#--- update graph
	def update_graph_plot(self, chart_type = 'histogram'):
		start = time.time() 
		if chart_type == 'histogram':                
			X = np.asarray(self.graph_X, dtype=np.float32)
			b = []
			for a in X:
				if len(b) == 0:
					b.append(a)
				else:
					b.append(a - 0.000001)        
					b.append(a)
			c = len(b)
			X = np.asarray(b, dtype=np.float32)
			
			Y1 = np.asarray(self.graph_Y1, dtype=np.float32)
			b = []
			for a in Y1:
				b.append(a)
				if len(b) != c:
					b.append(a)
			Y1 = np.asarray(b, dtype=np.float32)
			
			Y2 = np.asarray(self.graph_Y2, dtype=np.float32)
			b = []
			for a in Y2:
				b.append(a)
				if len(b) != c:
					b.append(a)
			Y2 = np.asarray(b, dtype=np.float32)
		else:
			X = np.asarray(self.graph_X, dtype=np.float32)
			Y1 = np.asarray(self.graph_Y1, dtype=np.float32)
			Y2 = np.asarray(self.graph_Y2, dtype=np.float32)

		self.p1.clear()
		self.p2.clear()
		
		self.p1.plot(X,Y1,pen=self.pen_Y1, name="V")
		self.p2.addItem(pg.PlotCurveItem(X,Y2,pen=self.pen_Y2, name="I"))        

		a = (time.time() - start) * 1000.0
		self.label_plot_rate.setText(("Plot Rate  : %8.3fms" % (a)))
		
#--- file handling
	def file_open(self):
		filename = QFileDialog.getOpenFileName(self, "Open File", '', 'CSV(*.csv)')
		if filename[0] != '':
			self.CSV_file = filename[0]
		if self.CSV_file != '':
			self.open_CSV(self.CSV_file)    
	
	def file_save(self):
		filename, _ = QFileDialog.getSaveFileName(self, "Save File", datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")+".csv", "All Files (*);; CSV Files (*.csv)")
		rows = zip(self.graph_X, self.graph_Y1, self.graph_Y2)
		self.save_CSV(filename, rows)

	def save_CSV(self, filename='output.csv', rows=None):
		if rows is None:
			rows = []
		try:
			# Ensure directory exists
			directory = os.path.dirname(filename)
			if directory and not os.path.exists(directory):
				os.makedirs(directory)
			
			# Open file with explicit newline handling (prevents blank lines on Windows)
			with open(filename, 'w', newline='') as f:
				writer = csv.writer(f)
				# Write header first (example)
				writer.writerow(['Time (s)', 'Voltage (V)', 'Current (A)'])
				# Write data rows
				for row in rows:
					writer.writerow(row)
			logger.info(f"CSV saved successfully to {filename}")

		except PermissionError:
			logger.error(f"Permission denied when writing to {filename}")
			#self.show_status_message("Permission denied: check folder access rights")
		except FileNotFoundError:
			logger.error(f"Invalid path or file name: {filename}")
			#self.statusBar().showMessage("Invalid file path")
		except OSError as e:
			logger.error(f"OS error saving CSV: {e}")
			#self.show_status_message("Disk or file system error")
		except Exception as e:
			# Fallback for any other unexpected error
			logger.error(f"Unexpected error saving CSV: {e}")
			#self.show_status_message("Unknown error saving file")

#--- thread related code
	def progress_fn(self, n):
		logger.info("%d%% done" % n)
		
	def print_output(self, s):
		pass
		
	def thread_complete(self):
		pass
	
#--- buttons
	def pushButton_save_plot_clicked(self):
		self.file_save()

	def pushButton_clear_plot_clicked(self): 
		self.graph_X = []
		self.graph_Y1 = []
		self.graph_Y2 = []
		self.time_old = time.time()
		self.p1.clear()
		self.p2.clear()
		self.capacity_time_old = time.time()
		self.capacity = 0.0
		
	def radioButton_lock_clicked(self):
		if self.serialconnected:
			if self.radioButton_lock.isChecked():
				self.pass_2_thread(self.lock_on_change)
			else:
				self.pass_2_thread(self.lock_off_change)
	
	# pass_2_thread - radioButton_lock_clicked
	def lock_on_change(self, progress_callback):
		self.pass_2_dps('lock', 'w', 1.0)
		
	def lock_off_change(self, progress_callback):
		self.pass_2_dps('lock', 'w', 0.0)

	def pushButton_onoff_clicked(self):
		if self.serialconnected:
			if self.pushButton_onoff.isChecked():
				self.pushButton_on_start_time = time.time()
				self.pass_2_thread(self.on_change)
			else:
				self.pushButton_on_start_time = 0
				self.pass_2_thread(self.off_change)
				print("off_checkedclear: ")
		else:
			self.pushButton_onoff.setChecked(False)
			print("setchecked: ")
	
	# pass_2_thread - pushButton_onoff_clicked
	def on_change(self, progress_callback):
		self.pass_2_dps('onoff', 'w', 1.0)
		
	def off_change(self, progress_callback):
		self.pass_2_dps('onoff', 'w', 0.0)
		
	# PSU mode - import values
	def pushButton_set_clicked(self):
		if self.serialconnected:                   
			if self.lineEdit_vset.text() != '' or self.lineEdit_iset.text() != '':
				try:
					value1 = abs(float(self.lineEdit_vset.text()))        # added abs() to prevent applying incorrect sign
				except ValueError:
					self.lineEdit_vset.setText("Number ?")
					return
				try:
					value2 = abs(float(self.lineEdit_iset.text()))
				except ValueError:
					self.lineEdit_iset.setText("Number ?")
					return
				self.dps_mode = 0
				self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
	
	# Nicad mode - import values
	def pushButton_set_2_clicked(self):
		if self.serialconnected:                 
			if self.lineEdit_vset_2.text() != '' or self.lineEdit_iset_2.text() != '' or self.lineEdit_term_2.text() != '':
				try:
					value1 = abs(float(self.lineEdit_vset_2.text()))        # added abs() to prevent applying incorrect sign
				except ValueError:
					self.lineEdit_vset_2.setText("Number ?")
					return
				try:
					value2 = abs(float(self.lineEdit_iset_2.text()))
				except ValueError:
					self.lineEdit_iset_2.setText("Number ?")
					return
				try:
					value3 = abs(float(self.lineEdit_term_2.text()))
				except ValueError:
					self.lineEdit_term_2.setText("Number ?")
					return
				self.dps_mode = 1
				self.v_terminate = value3
				self.v_peak = 0
				self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
	
	# Li-ion mode - import values
	def pushButton_set_3_clicked(self):
		if self.serialconnected:                 
			if self.lineEdit_vset_3.text() != '' or self.lineEdit_iset_3.text() != '' or self.lineEdit_term_3.text() != '':
				try:
					value1 = abs(float(self.lineEdit_vset_3.text()))        # added abs() to prevent applying incorrect sign
				except ValueError:
					self.lineEdit_vset_3.setText("Number ?")
					return
				try:
					value2 = abs(float(self.lineEdit_iset_3.text()))
				except ValueError:
					self.lineEdit_iset_3.setText("Number ?")
					return
				try:
					value3 = abs(float(self.lineEdit_term_3.text()))        
				except ValueError:
					self.lineEdit_term_3.setText("Number ?")
					return
				self.dps_mode = 2
				self.i_terminate = value3
				self.pass_2_dps('write_voltage_current', 'w', [value1, value2])             
	
	def pushButton_connect_clicked(self):
		if self.pushButton_connect.isChecked():
			self.serial_connect()
			self.pushButton_CSV_view.setEnabled(False)
			self.pushButton_CSV.setEnabled(True)
			#self.pushButton_CSV_view.setText("")
		else:
			self.serial_disconnect("Disconnected")
			self.pushButton_CSV_view.setEnabled(True)
			self.pushButton_CSV.setEnabled(False)
			#self.pushButton_CSV_view.setText("CSV view")
	
	def pushButton_CSV_clicked(self):
		if self.serialconnected:
			if len(self.CSV_list) > 0:
				self.dps_mode = 3                # set to CSV mode
				self.timer2.start()        # begin 
			else:
				self.pushButton_CSV.setChecked(False)
		else:
			self.pushButton_CSV.setChecked(False)
	
	def pushButton_CSV_clear_clicked(self):
		self.stop_CSV()

	def pushButton_CSV_view_clicked(self):
		if len(self.CSV_list) > 0:
			if self.serialconnected == False:        
				self.graph_X = [row[0] for row in self.CSV_list]                # Xaxis  - time interval
				self.graph_Y1 = [row[1] for row in self.CSV_list]                                # Y1axis - voltage
				self.graph_Y2 = [row[2] for row in self.CSV_list]                                # Y2axis - current
				self.update_graph_plot()
			else:
				pass
				
#--- import CSV file        
	def open_CSV(self, filename):
		self.CSV_list = []
		try:
			with open(filename, 'r') as f:
				csvReader = csv.reader(f)
				next(csvReader, None)                       # skips header
				data_list = list(csvReader)
				for row in data_list:
					if len(row) > 2:
						self.CSV_list.append(row)
			self.labelCSV(len(self.CSV_list))   
		except Exception as e:
			logger.error(f"Error reading CSV file: {e}")
			
	def labelCSV(self, value):          # display remaining steps
		self.label_CSV.setText("Steps remaining: %3d" % value)

#--- action the imported CSV using timer2       
	def action_CSV(self):
		if self.pushButton_onoff.isChecked() == True: 
			if self.dps_mode != 3:
				return  
			if len(self.CSV_list) > 0:
				data_list = self.CSV_list
				if len(self.CSV_list) > 1:                        # calculate step time interval
					value0 = float(data_list[1][0]) - float(data_list[0][0])
				else:
					value0 = 1.0  # Default to 1 second if only one entry
				# set Voltage/Current levels
				value1 = float(data_list[0][1])
				value2 = float(data_list[0][2])
				self.pass_2_dps('write_voltage_current', 'w', [value1, value2])
				
				data_list.pop(0)
				self.labelCSV(len(self.CSV_list))         # display No. of remaining steps
				
				# Stop and restart timer with proper interval
				self.timer2.stop()
				interval_ms = max(100, int(value0 * 1000))  # Minimum 100ms, convert seconds to milliseconds
				self.timer2.setInterval(interval_ms)
				self.timer2.start()
			else:
				self.stop_CSV()
				self.pushButton_CSV.setChecked(False)
				self.pass_2_thread(self.off_change)

	def stop_CSV(self):
		self.timer2.stop()
		self.CSV_list = []
		self.labelCSV(len(self.CSV_list)) 
		self.dps_mode = 0        # return to PSU mode
		
#--- slider 
	def horizontalSlider_brightness_sliderReleased(self):
		self.pass_2_thread(self.slider_change)

	def horizontalSlider_brightness_sliderMoved(self):
		self.slider_in_use = True

# pass_2_thread - horizontalSlider_brightness_valueChanged
	def slider_change(self, progress_callback):
		value = self.horizontalSlider_brightness.value()
		logger.info("slider: ", self.horizontalSlider_brightness.value(), type(self.horizontalSlider_brightness.value()))
		self.pass_2_dps('b_led', 'w', value)
		self.slider_in_use = False

#--- thread the needle  
	def pass_2_thread(self, func):
		# Pass the function to execute
		worker = Worker(func) # Any other args, kwargs are passed to the run function
		worker.signals.result.connect(self.print_output)
		worker.signals.finished.connect(self.thread_complete)
		worker.signals.progress.connect(self.progress_fn)
		self.threadpool.start(worker)

#--- loop is actioned from timer1, reading data & controlling charging  
	def loop_function(self):
		try:
			self.read_all()
			self.operating_mode()
		except Exception as e:
			logger.error(f"Error in loop_function: {e}")
			traceback.print_exc()
			self.serial_disconnect("Disconnected")
			
#--- operating mode 
	def operating_mode(self):
		value = self.dps_mode
		if value == 0:
			self.label_operating_mode.setText('PSU')
		elif value == 1:
			self.label_operating_mode.setText('NiCad')
			if float(self.vout) > float(self.v_peak):   # find peak voltage
				self.v_peak = float(self.vout)
			if self.pushButton_onoff.isChecked() and (time.time() - self.pushButton_on_start_time > 5): # adds 5sec delay, to prevent immediate switch OFF
				if float(self.vout) <= (self.v_peak - float(self.v_terminate)):     # switch off output
					self.pushButton_onoff.setChecked(False)
					self.pushButton_onoff_clicked()
		elif value == 2:
			self.label_operating_mode.setText('Li-Ion')
			if self.pushButton_onoff.isChecked() and (time.time() - self.pushButton_on_start_time > 5): # adds 5sec delay, to prevent immediate switch OFF  
				if float(self.iout) <= float(self.i_terminate):         # switch off output
					self.pushButton_onoff.setChecked(False)
					self.pushButton_onoff_clicked()
		elif value == 3:
			self.label_operating_mode.setText('CSV')
		else:
			self.label_operating_mode.setText('Invalid')

	def accrued_capacity(self, current):
		if self.capacity_time_old != '':
			self.capacity_time_current = time.time()
			self.capacity_time_interval = self.capacity_time_current - self.capacity_time_old
			self.capacity_time_old = self.capacity_time_current
			try:
				self.capacity = self.capacity + ((self.capacity_time_interval / 3600.0) * float(current))
			except ZeroDivisionError:
				self.capacity =  0.0
			self.label_capacity.setText("Capacity   : %8.3fAh" % self.capacity)
		else:
			self.capacity_time_old = time.time()
			
#--- read & display values from DPS 
	def read_all(self):
		data = self.pass_2_dps('read_all')
		if data and len(data) >= 13:
			if data != False:       
				self.vout = ("%5.2f" % data[2]) # vout
				self.iout = ("%5.3f" % data[3]) # iout
				
				self.accrued_capacity(self.iout)
				
				self.time_interval = time.time() - self.time_old                        
				self.graph_X.append(self.time_interval)                # Xaxis  - time interval
				self.graph_Y1.append(self.vout)                                # Y1axis - voltage
				self.graph_Y2.append(self.iout)                                # Y2axis - current
				
				self.update_graph_plot()
				
				self.lcdNumber_vset.display("%5.2f" % data[0])  # vset
				self.lcdNumber_iset.display("%5.3f" % data[1])  # iset
				self.lcdNumber_vout.display(self.vout)  # vout
				self.lcdNumber_iout.display(self.iout)  # iout
				
				self.lcdNumber_pout.display("%5.2f" % data[4])  # power
				self.lcdNumber_vin.display("%5.2f" % data[5])       # vin
				
			# lock
				value = data[6]
				if value == 1:
					self.radioButton_lock.setChecked(True)
				else:
					self.radioButton_lock.setChecked(False)
					
			# protection
				value = data[7]
				if value == 1:
					self.label_protect.setText('Protection :   OVP')
				elif value == 2:
					self.label_protect.setText('Protection :   OCP')
				elif value == 3:
					self.label_protect.setText('Protection :   OPP')
				else:
					self.label_protect.setText('Protection :   OK')
				
			# cv/cc 
				if data[8] == 1:
					self.label_cccv.setText('Mode        :   CC')
				else:
					self.label_cccv.setText('Mode        :   CV')

			# on/off    
				value = data[9]
				if value == 1:
					self.label_onoff.setText('Output      :   ON')  # on/off
					self.pushButton_onoff.setChecked(True)
					self.pushButton_onoff.setText("ON")
				else:
					self.label_onoff.setText('Output      :   OFF') # on/off
					self.pushButton_onoff.setChecked(False)
					self.pushButton_onoff.setText("OFF")

			# slider    
				value = int(data[10])
				if isinstance(value, int):
					if self.slider_in_use == False:
						self.horizontalSlider_brightness.setValue(value)    # brightness
						self.label_brightness.setText('Brightness Level:   %s' % value)
				
				self.label_model.setText("Model       :   %s" % data[11])   # model
				self.label_version.setText("Version     :   %s" % data[12]) # version
		else:
			logger.error(f"Received incomplete data packet: length {len(data) if data else 0}")

	def pass_2_dps(self, function, cmd="r", value=0.0):
		"""Send commands to DPS device via serial communication."""
		status = False
		if self.dps is None:
			logger.error("DPS device not initialized")
			return status
		if self.serialconnected:
			start_time = time.time()
			self.mutex.lock()
			try:
				# Validate inputs
				if not isinstance(value, list):
					if not isinstance(value, float):
						value = float(value)
						
				if not isinstance(function, str) or not function:
					raise ValueError("Invalid function name")
				
				# Create a whitelist of allowed functions
				allowed_functions = {
					'lock': self.dps.lock,
					'onoff': self.dps.onoff,
					'b_led': self.dps.b_led,
					'read_all': self.dps.read_all,
					'write_voltage_current': self.dps.write_voltage_current
				}
				
				if function not in allowed_functions:
					raise ValueError(f"Function '{function}' not allowed")
				
				# Execute the function safely
				method = allowed_functions[function]
				result = method(cmd, value)
				
				# Update data rate display
				elapsed_time = (time.time() - start_time) * 1000.0
				self.label_data_rate.setText(f"Data Rate : {elapsed_time:8.3f}ms")
				status = result
				
			except Exception as e:
				logger.error(f"Communication error: {e}")
				self.label_data_rate.setText("Data Rate : Error")
				logger.info("Exception: ", function, cmd, value)
			self.mutex.unlock()
		return status
			

#--- serial selection setup       
	def combobox_populate(self):        # collects info on startup                
		self.comboBox_datarate.clear()
		self.comboBox_datarate.addItems(["9600", "2400", "4800", "19200"])  # note: 2400 & 19200 doesn't seem to work

#--- serial port stuff  
	def scan_serial_ports(self):
		if sys.platform.startswith('win'):
			ports = ['COM%s' % (i + 1) for i in range(256)]
		elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
			# this excludes your current terminal "/dev/tty"
			ports = glob.glob('/dev/tty[A-Za-z]*')
		elif sys.platform.startswith('darwin'):
			ports = glob.glob('/dev/tty.*')
		else:
			raise EnvironmentError('Unsupported platform')

		result = []
		for port in ports:
			try:
				s = serial.Serial(port, timeout=0.1)
				s.flush()
				s.close()
				result.append(port)
			except (OSError, serial.SerialException):
				pass
		return result

	def test_serial_connect(self, port):
		self.serialconnected = False
		try:
			baudrate = abs(int(self.comboBox_datarate.currentText()))
			slave_addr = abs(int(self.lineEdit_slave_addr.text()))
			ser = Serial_modbus(port, slave_addr, baudrate, 8)
			self.dps = Dps5005(ser, self.limits) #example '/dev/ttyUSB0', 1, 9600, 8)
			if self.dps.version() > 0:
				self.serialconnected = True
				self.pushButton_connect.setText("Connected")
				self.timer.start()
				if self.time_old == "":
					self.time_old = time.time()
				logger.info(f"Connected to {port} with baudrate {baudrate}, slave address {slave_addr}")
				self.pushButton_CSV_view.setEnabled(False)                # disable CSV viewing capability
				self.pushButton_clear_plot_clicked()                        # clear plot
		except Exception as e:
			logger.error(f"Failed connection attempt on {port}: {e}")
		return self.serialconnected

	def serial_connect(self): # port autoconnects, baud rate & slave address manual inputs
		try:
			if self.limits.port_set != "":								# Manual port definition in .ini file
				if self.test_serial_connect(self.limits.port_set): 
					return
			for port in self.scan_serial_ports():						# Automatic port scan
				if self.test_serial_connect(port): 
					return
			self.serial_disconnect("No device found!")
		except Exception as detail:
			logger.error(f"General error in serial_connect: {detail}")
			self.serial_disconnect("Try again !!!")

	def serial_disconnect(self, status):
		self.shutdown()
		self.serialconnected = False
		self.timer.stop()
		self.pushButton_connect.setText(status)
		self.pushButton_connect.setChecked(False)
		self.combobox_populate()
		self.pushButton_CSV_view.setEnabled(True)                                                # enable CSV viewing capability
		logger.info(status)
		
app = QApplication(sys.argv)
widget = dps_GUI()
widget.show()

sys.exit(app.exec_())

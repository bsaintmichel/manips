# -*- coding: utf-8 -*-
"""
Created on Wed Jun  7 18:29:00 2023

@author: Brice
"""

""" SENSORTOOLS : Brice's (simplified) routines to handle the Arduino sensors 
(sensor 1 and 2, then humidity and temperature)
    it works using a class called Sensor
    """

import serial
import time
import numpy as np
    
class Sensor():
    """ A class to manage the Pressure and the Humidity sensors
    through the ARDUINO board. 

    NOTE: UPDATE from 2024, I NO LONGER CONVERT THE VOLTAGE OF
    THE PRESSURE SENSOR TO AN ACTUAL PRESSURE IN THE ARDUINO
    CODE. Please specify which sensor you have (`ptype`, either
    5010 or 5100) when initializing the sensor here. 

    ARGS
    ----
    * port ['COM1', 'COM2',  ...] : your COM port for the ARDUINO board
    * baudrate [default 115200, I would leave it to that]
    * ptype [default 5010, also 5100 possible] : the pressure type 
        - MPX5010 goes to 0.1 bar
        - MPX5100 goes to 1.0 bar 
    """

    def __init__(self, port='COM4', baudrate=115200, ptype='5010'):

        self.port = port
        self.baudrate = baudrate
        self.ser = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=2)
        self.p = []
        self.ptype = ptype
        self.tlocal = []
        self.texp = []
        self.hum = []
        self.temp = []
    
        try:
            self.ser.open()
        except serial.SerialException:
            self.ser.close()
            self.ser.open()
        if self.ser.is_open:
            self.ser.flush()
            
    def read_buffer(self,timeout=1,verbose=False):
        """ A basic function to read all the contents of 
        the serial port corresponding to the pressure/humidity
        sensor """
         # Wait for reply to arrive
        t0 = time.time()
        has_timed_out = False
        old_bytes_received = -1
        new_bytes_received = 0

        while old_bytes_received != new_bytes_received and not has_timed_out:
            old_bytes_received = new_bytes_received
            new_bytes_received = self.ser.in_waiting
            has_timed_out = time.time() - t0 > timeout 
            time.sleep(0.05)
        
        if not has_timed_out:
            out = self.ser.read_all()
            if out is not None:
                out = out.decode().strip()
            else:
                return 0
            if verbose:
                print(f'Sensor >> read_one ; received "{out}"')
            if len(out) > 0:
                out = out.split('\r\n')
                n_lines = 0
                
                for line in out:
                    try: 
                        parts = line.split(' ')
                        tlocal = float(parts[0])
                        hum = float(parts[2])
                        temp = float(parts[3])
                        
                        # Pressure reading V -> Pa
                        factor = np.nan
                        vnormed = float(parts[1]) # Vnormed is actually Vmeas/Vs in the doc
                        if self.ptype == '5010': factor = 0.09
                        elif self.ptype == '5100': factor = 0.009
                        else: raise ValueError('Sensor type {self.ptype} not implemented !')

                        p = (vnormed-0.04)/factor*1e3
                            # Official formula is : Vmeas/Vs = p x 0.09  + 0.04 for 5010
                            #                       Vmeas/Vs = p x 0.009 + 0.04 for 5100
                            # My vnormed is between 0 and 1 (== Vmeas/Vs)
                        
                        self.texp.append(float(time.time()))
                        self.tlocal.append(tlocal)
                        self.p.append(p)
                        self.hum.append(hum)
                        self.temp.append(temp)
                        n_lines += 1
                        
                    except IndexError: # Basically incomplete or malformed line
                        pass
                    except ValueError:
                        pass
                return n_lines
            else:
                return 0
        else: # Timeout...
            return 0

    def close(self):
        """ CLOSE() : Stops the sensor and closes the connection """
        self.ser.close()
        
def acquire(sensor:Sensor, save_folder='.', max_time=10, rate=4, verbose=False, run_event=None):
    """ Read plenty of values from the sensor and do it until max_time 
    has elapsed. The 'rate' will be only roughly followed. If you want to interrupt 
    your acquisition midway, use a run_event object (from threading)
    """
    t_ini, t_now = time.time(), time.time()
    with open(save_folder + '/sensor_log.txt', 'w') as logfile:
        logfile.write('texp,tlocal,p1,p2,hum,temp\n')

    while t_now - t_ini <= max_time:
        if run_event is not None and not run_event.is_set():    # If main thread has told you to die, basically
            print('sensortools.acquire() >>  Aborted.')
            break
        t_now = time.time()
        nlines = sensor.read_buffer(verbose=verbose)
        dat_str = ''
        for idx in range(-nlines, 0):
            dat_str += f'{sensor.texp[idx]:.2f},{sensor.tlocal[idx]:.2f},{sensor.p1[idx]:.2f},{sensor.p2[idx]:.2f},{sensor.hum[idx]:.2f},{sensor.temp[idx]:.2f}\n'
        with open(save_folder + '/sensor_log.txt', 'a') as logfile:
            logfile.write(dat_str)
            
        time.sleep(1/rate)
    return 0

############# Quick test ##############################
#######################################################

if __name__ == '__main__':
    mysensor = Sensor(port='COM4', ptype=5010)
    acquire(mysensor, max_time=20, rate=3)
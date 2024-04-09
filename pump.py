import serial
import time
import pandas as pd
import numpy as np
import threading

class shared_var():
    """ A super duper simple shared variable 
    class"""
    def __init__(self, val=0):
        self.lock = threading.Lock()
        self.val = val

    def get(self):
        with self.lock:
            return self.val
        
    def set(self, val=0):
        with self.lock:
            self.val = val

class Pump():
    """ PUMP : Brice's (simplified) pump handling class
    that allows you to start, stop and monitor the pump
    without having to bother too much about the baud rate of 
    the serial port.

    NOTE: DEFAULT UNITS ARE µl, µl/min and mm !
     
    * To find the right COM port, you can use softwares like USBdeview
    * You can specify details of your sytinge now (using diameter / volume / syringe)
    or later. 
    NOTE : syringe naming convention can be found in the manual from Harvard Scientific 
    or by sending me (Brice) an email.
    """

    def __init__(self, port='COM3', 
                 reset=True, 
                 infuse_rate=200, 
                 withdraw_rate=200, 
                 diameter=None, 
                 svolume=None, 
                 ini_volume=0,
                 syringe=None):
        
        self.port = port
        self.baudrate = 19200
        self.parity = serial.PARITY_ODD
        self.stopbits = serial.STOPBITS_TWO
        self.bytesize = serial.SEVENBITS
        self.irate = infuse_rate
        self.wrate = withdraw_rate
        self.status = ':'
        self.msg = ''
        
        self.now_volume = 0 # The net _injected_ volume irrespective of the initial volume of gas/liquid 
                            # in the syringe
        self.ini_volume = ini_volume   # The amount of gas _initially_ present in the syringe
        self._ivol = [0,0,0,0]
        self._wvol = [0,0,0,0]

        print(f'pump.__init__ >> Connecting to port {self.port} ...')

        self.ser = serial.Serial(port=self.port, baudrate=self.baudrate,
                            parity=self.parity, stopbits=self.stopbits,
                            bytesize=self.bytesize, timeout=2)
        
        if not self.ser.is_open:
            print(f'pump.__init__>> Cannot connect to pump')
            return None
            
        ## Forces the "ultra" commands. At some point it had reversed on its own
        # to the "22" and "44" commands and I did not understand ANYTHING
        # anymore. So I am leaving it "just in case"...
        self.write('cmd ultra')
        self.write('smooth on')

        if reset: 
            self.write('cvolume')
            self.write('ctime')

        ## Check the details of the syringe and infusion if parameters have
        # not been specified before ; otherwise apply them
        if syringe: self.syringe = self.write(f'syrmanu {syringe}')
        else: self.syringe = self.write(f'syrmanu')

        if not diameter: self.diameter = float(self.write(f'diameter').split(' ')[0])
        else: self.write(f'diameter {diameter} mm')
        
        if not svolume: self.svolume = _convert_volume(self.write(f'svolume'))
        else: self.write(f'svolume {svolume} ul')

        self.write(f'irate {infuse_rate} u/m')
        self.write(f'wrate {withdraw_rate} u/m')

        print(f'pump.__init__ > Syringe is {self.syringe} / volume {self.svolume}, diameter {self.diameter}')        

    def write(self, cmd:str, timeout=2, verbose=False) -> str:
        """ An I / (then) / O method
         to talk to the syringe pump via the 
        serial port and read the answer (if there is one)
           
        ARGS
        -----
        * cmd (string) : the command you want to run (check the manual of the PhD Ultra)
        * timeout (float, in seconds) : when to give up with a command
        * verbose (bool, default False) : if you want to display each raw message received 

        RETURNS
        ------
        * msg (string) : the **processed** answer from the pump. 
        NOTE : the processed message AND the pump status are also added 
        to the "pump" object as `self.msg` and `self.status` (if message 
        was received successfully)
        """
        valid_status = set([':', '>', '<', '*', ':', 'T*'])
        message = ''
        out = b''
        status = self.status

        # Send command
        cmd = cmd + '\r\n'
        try:
            self.ser.write(cmd.encode())
            self.ser.flush()
        except serial.SerialTimeoutException:
            print(f'pumptools.PhDUltraPump.write >> Sending message timed out')
        
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
        
        out = self.ser.read_all()
        parts = []
        if out is not None:
            parts = out.decode().split('\n') # This separates actual lines
            parts = list(map(lambda str: str.strip('\r'), parts))

        if verbose:
            print(f'pumptools.PhDUltraPump.write >> Raw sent : {cmd.encode()}, Received raw : "{out}"')
            
        if len(parts) >= 3: 
            status = parts[-1] 
            if parts[-2] in valid_status:  # Weird Case no1 : e.g. b'\n19.988 seconds\r\n>\r\nT*'
                message = parts[1]
            else:                          # Weird Case no2 : e.g. b'\r\nT*\n10.0011 ul\r\nT*' or normal case, e.g. b'\n2.28205 ul\r\n<'   
                message = parts[-2]         
        if len(parts) == 2: 
            message = ''
            status = parts[1].strip('\n')
        elif len(parts) <= 1:
            print(f'pumptools.PhDUltraPump.write >> Warning : received raw message "{out}" and I cannot understand it')
        
        # Update pump object and return message because we are nice
        if status in valid_status:
            self.status = status
        else: 
            print(f'pumptools.PhDUltraPump.write >> Warning : Odd status {status} from message {out} ... maybe a fluke. Ignoring it for now ...')
        self.msg = message
        return message

    def write_safe(self, cmd:str, timeout=2, verbose=False) -> None:
        """ A wrapper on "pump.write" that checks more thoroughly
        __what__ the syringe pump answers you when you want to do things
        (sometimes it gets your orders wrong). Works mostly with "load XXXX" 
        and numerical value commands e.g. `tvolume 5 ul`, `irate 5 u/m`, ...
        but not sure whether it works with all the commands.

        ARGS
        -----
        * cmd (string) : the command you want to run , __with parameters__ (e.g. tvolume : 1 ul)
        * timeout (float, in seconds) : when to give up with a command
        * verbose (bool) : ask whether you want a 

        RETURNS
        -----
        * Nothing. It will still apply the command, though, 
        and it will print, though, a string telling you what was sent / the expected answer / the received answer.

        """

        if 'load' in cmd:
            answers_dict = {'qs w':'Quick Start - Withdraw only', 'qs i':'Quick Start - Infuse only'}
            expected_answer = answers_dict.get(cmd.strip('load '), cmd.strip('load ')) # If key is not in dict, return key instead of match
            base_command = 'mode'
            answer = ''
        else: # Command with a numerical value. Bloody rates
            base_command =  cmd.split(' ')[0]
            expected_answer = cmd.lstrip(base_command).lstrip()
            expected_answer = expected_answer.replace('u/', 'ul/')
            expected_answer = expected_answer.replace('m/', 'ml/')
            expected_answer = expected_answer.replace('n/', 'nl/')
            expected_answer = expected_answer.replace('/m', '/min')
            expected_answer = expected_answer.replace('/s', '/sec')
            expected_answer = expected_answer.replace('/h', '/hr')
            answer = ''

        _ = self.write(cmd, timeout=timeout, verbose=verbose)
        answer = self.write(base_command, timeout=timeout, verbose=verbose)
        t0 = time.time()
        while answer != expected_answer and time.time() - t0 < timeout:
            answer = self.write(base_command, timeout=timeout)
            print(f'pumptools.PhDUltraPump.write_safe >> sent "{cmd}" then "{base_command}" and  received "{answer}" instead of "{expected_answer}"')
            time.sleep(0.25)

    def start(self, mode='infuse', reset=True, tvolume=None, rate=None, quiet=False) -> None:
        """ Starts the pump. Default `mode` is infusing.
        Can call routines you have programmed in the pump.
        
        Args
        -----
        * mode ['infuse' / 'withdraw' / or any method stored in the PhD Ultra] : your preferred function mode from the pump
        * tvolume [int, in µl] : your target volume
        * reset [bool, default True] : whether you want to reset your infused/withdrawn volumes, etc. before you start your step
        * rate [int, in µl/min] : your infuse rate.
        * quiet [default False] : remove output
        """
        if reset:
            self.write(f'cvolume')
            self.write(f'ctime')

        if tvolume:
            self.write_safe(f'tvolume {tvolume} ul')

        if not quiet: print(f'pump.start > Starting {mode} / rate {rate} / tvolume {tvolume}')
        
        if mode != '0' or mode != 'stop': 
            if mode == 'infuse' or mode == 'i':
                rate_word = 'irate'
                mode = 'qs i'
                if self.irate != rate:
                    self.write_safe(f'{rate_word} {rate} u/m')
                
            elif mode == 'withdraw' or mode == 'w':
                rate_word = 'wrate'
                mode = 'qs w'
                if self.wrate != rate:
                    self.write_safe(f'{rate_word} {rate} u/m')
            
            self.write_safe(f'load {mode}')
            self.write('run')
            
    def stop(self, quiet=False) -> None:
        """ STOP() : Stops the pump. D'uh. """
        if not quiet: print(f'pump.stop > Stopped')
        self.write('stop') 

    def read(self) -> None:
        """ READ : Read the current values of : 
        - infuse / withdraw volume 
         (i.e. infused volume / time and withdraw volume / time) 
         while the pump is running ! 
         It updates the `now_volume` which basically keeps track of the 
          **TOTAL INJECTED VOLUME** (so injection means + )
         """
        
        self._ivol[0] = _convert_volume(self.write('ivolume'))
        self._wvol[0] = _convert_volume(self.write('wvolume'))
        self._ivol = _keep_track(self._ivol)
        self._wvol = _keep_track(self._wvol)
        self.now_volume = (self._ivol[3]-self._wvol[3])


    def close(self) -> None:
        """ CLOSE() : Stops the pump and closes the connection """
        self.stop()
        self.ser.close()

def run_sequence(pump:Pump, sequence:pd.DataFrame, save_folder='.', run_event=None, quiet=False):
    """ RUN_SEQUENCE() :  Sequence launch for the pump. 
    Allows you to do injection / stop / withdraw steps as you will 
    and do all kinds of wacky things. The programme also monitors
    what the pump is doing while it is doing it. 
    
    ARGS
    ----
    * pump [class Pump from this file] : your PhD Ultra pump (--> go create one it) 
    * sequence [pd.DataFrame] : a sequence produced, e.g. from make_sequence 
    from the same file. Should contain a list of steps, durations, volumes, etc.
    * save_folder = where you want to save the log file of the pump. 
    NOTE : the injected volume and widthdrawn volume are stored in different variables
    (and same for injection and withdrawal times) ...
    * run_event [threading.Event() or None] : an 'event' object allowing you to terminate
    the sequence from the main thread when the "is_set" property is deactivated.
    * quiet (default False) : if you don't want any output from the program
    """

    headerstr = f'{"step":5s}\t{"texp":8s}\t{"cycle":5s}\t{"rep":5s}\t{"volum":8s}\t{"status":6s}'
    if not quiet: print(headerstr)
    with open(save_folder + '/pump_log.txt', 'w') as logfile:
        logfile.write(headerstr.replace('\t', ',') + '\n')

    t0 = time.time()
    for no, step in sequence.iterrows():
        t_seq = time.time()
        stay_in_step = True

        if step['type'] != '0': 
            pump.start(reset=False, mode=step['type'], rate=step['rate'], tvolume=step['volume'], quiet=True)
        elif pump.status not in ('T*','*',':'): # If step['type'] == '0', normally we should already have stopped, but we still do it in case we have issues.
            pump.stop(quiet=False)

        while stay_in_step:
            if step['type'] != '0':
                stay_in_step = (pump.status != 'T*') and (time.time() - t_seq <= step['duration']*1.25)        # If we stay in the step too long, there must be an issue ...
            else:
                stay_in_step = (time.time() - t_seq <= step['duration'] + 0.5)

            pump.read()

            datastr = f'{no:5d}\t{time.time()-t0:8.2f}\t{step["cycle"]:5d}\t{step["repeat"]:5d}\t{pump.now_volume:8.2f}\t{pump.status:6s}\t{step["time"]}'
            if not quiet: print(datastr)
            with open(save_folder + '/pump_log.txt', 'a') as logfile:
                logfile.write(datastr.replace('\t', ',') + '\n')
            
            if pump.status == '*':
                print('pump.run_sequence > Motor Stalled.')

            if run_event is not None and not run_event.is_set(): # Kill immediately if term signal sent
                pump.stop()
                print('pump.run_sequence > Aborted.')
                return 0
            
            time.sleep(0.25)
                    
    print('pump.run_sequence > Run Complete.')
    return 0
    
    
def regulate(pump:Pump, p_measure:shared_var, p_target:float, 
             abort_thread=None, reverse=False, rate=1000, max_time=100,
             absolute_tolerance=200.0, relative_tolerance=0.015,
             save_folder='.', quiet=False) -> None:
    """ A function to regulate the pressure by withdrawing/injecting gas from the syringe.
    
    ARGS
    -----

    * p_measure : your pressure measurement (can come from another process / thread, needs to be updated)
    * p_target : the pressure you want to apply (can also theoretically change with time)
    * abort_process [threading.Event] : so you can kill the thread from main thread
    * max_time : maximum time for the regulation
    * rate : the injection / withdrawal rate 
    * absolute_tolerance [float] : the absolute tolerance we allow for the pressure measurement compared to the target
    * relative_tolerance [float] : the relative tolerance we allow for the pressure measurement compared to the target
    * reverse [default False] : if False : we INJECT to increase p_measure 
                                if True  : we WITHDRAW to increase p_measure
    * save_folder [default '.'] : the save folder we are using 
    * quiet [default False] : remove standard output
    """

    t0 = time.time() 
    pump.write(f'cvolume')
    pump.write(f'irate {rate} u/m')
    pump.write(f'wrate {rate} u/m') 

    print(f'pump.regulate > Target is {p_target} / i&w rate {rate} / reverse {reverse} / max time {max_time} / initial volume in syringe {pump.ini_volume}')

    headerstr = f'{"time":8s}\t{"pmeas":8s}\t{"ptarg":8s}\t{"status":6s}\t{"injvol":8s}\t{"syrvol":8s}\t{"gorev"}\t{"gofwd"}\t{"syrend"}'
    if not quiet: print(headerstr)
    with open(save_folder + '/pump_log.txt', 'w') as logfile:
        logfile.write(headerstr.replace('\t', ',') + '\n')
    
    try:
        while time.time() - t0 < max_time:

            # Abort if something happens
            if abort_thread is not None and not abort_thread.is_set():
                pump.stop()
                print('pump.regulate > Aborted.')
                break
            
            # Measure volumes / NOTE : infused / withdrawn volumes are
            # equal to zero when we are idle / in the wrong direction
            pump.read()
            
            # Decide what to do based on inputs
            pnow = p_measure.get()
            stop_incr  = np.isfinite(pnow) and (pnow >= p_target)
            start_incr  = np.isfinite(pnow) and (pnow < (1-relative_tolerance)*p_target - absolute_tolerance/2)
            start_decr = np.isfinite(pnow) and (pnow > (1+relative_tolerance)*p_target + absolute_tolerance/2)
            stop_decr = np.isfinite(pnow) and (pnow <= p_target)

            syrvol = pump.ini_volume - pump.now_volume
            syr_end  = (syrvol < 0.02*pump.svolume) or (syrvol > 0.98*pump.svolume)
            is_fwd = pump.status == '>'
            is_rev = pump.status == '<'
            is_idle  = pump.status == ':' or pump.status == '*'

            go_fwd = is_idle and start_incr and not syr_end
            go_rev = is_idle and start_decr and not syr_end

            # Stop conditions are slightly different between
            # forward and reverse ; go conditions are reversed
            if not reverse:
                stop = (is_fwd and stop_incr) \
                    or (is_rev and stop_decr) \
                    or syr_end    
            if reverse:
                stop = (is_rev and stop_incr) \
                    or (is_fwd and stop_decr) \
                    or syr_end
                go_fwd, go_rev = go_rev, go_fwd

            if go_fwd:
                pump.write('load qs i')
                pump.write('run')
            if go_rev:
                pump.write('load qs w')
                pump.write('run')
            elif stop:
                pump.stop(quiet=True)

            time.sleep(0.33)

            datastr = f'{time.time()-t0 :8.2f}\t{pnow:8.1f}\t{p_target:8.1f}\t{pump.status:6s}\t{pump.now_volume:+8.2f}\t{syrvol:+8.2f}\t{go_rev}\t{go_fwd}\t{syr_end}'
            if not quiet: print(datastr)
            with open(save_folder + '/pump_log.txt', 'a') as logfile:
                logfile.write(datastr.replace('\t', ',') + '\n')                 
    finally:
        pump.stop(quiet=True)
    
############################################################################################
### UTILITY FUNCTIONS .... #################################################################

def _keep_track(vals:list):
    """ Keeps track of the syringe volume by doing operations
    on the withdrawn / injected volumes as a function of time.

    0 : current (raw) reading
    1 : previous (raw) reading
    2 : reference reading (from last i/w step)
    3 : cumulative reading (current + reference)
    """
    
    if vals[0] == 0 and vals[1] > 0:    # We have just stopped --> save last good value
        vals[2] += vals[1]
        vals[3] = vals[2]
    elif vals[0] > 0:                   # We are moving : add ref to whatever we have now
        vals[3] = vals[2] + vals[0]

    # Then shift bits 
    vals[1] = vals[0]    

    return vals


def _convert_time(time_str : str) -> float:
    """ Converts the time str sent by
        the pump into a useful float in s
    """
    time_str = time_str.replace('\r', '')
    try:
        if 'seconds' in time_str:
            tval = float(time_str.split(' ')[0])
        elif ':' in time_str:
            hh, mm, ss = time_str.split(':')
            tval = int(hh)*3600 + int(mm)*60 + int(ss)
        else:
            print(f'{time_str} ??' )
            tval = np.nan
        return tval
    except ValueError:
        return np.nan

def _convert_volume(volume_str : str) -> float:
    """ Converts the volume str sent by the pump
     into a useful volume float in µl """
    volume_str = volume_str.replace('\r', '')
    if 'ul' in volume_str or 'ml' in volume_str or 'nl' in volume_str:
        volume_str = volume_str.lstrip('T*') # If target volume reached, it adds T* to the string ...
        vval, vunit = volume_str.split(' ')
        vval = float(vval)
        if vunit == 'ml':
            vval = vval*1000
        elif vunit == 'nl':
            vval = vval/1000
        return vval
    else: 
        return np.nan

def make_sequence(volume=[0], rate=[1], duration=[1], repeat=[1], cycle_kind='i0w0', center=False):
    """ A routine that creates your sequence for you. 
    ARGS
    ----
    * volume [list]: the injected or withdrawn volumes
    * rate [list] : the rate at which you want to inject / withdraw
    * duration [list] : the duration you want to stop the pump between steps (if you want to do so) / NOTE : for injection & withdraw, these values will be recomputed anyway.
    * repeat [list] : the number of times you want to re-do a typical cycles
    * cycle-kind [str] : the nature of your cycle, including 'i' (inject), 'w' (withdraw), '0' (stop). Parameters will be constant during these cycles.
    * center [bool] : only applies for 'i0w0' cycles: in this case will oscillate around an equilibrium radius (i.e. first inject/withdraw step
    will have a volume divided by two) instead of injecting then withdrawing all the time the same amount. 
    NOTE : centering will logically mess up a bit your first cycle, and your last cycle. Recommended to do more than two repeats then. 
    NOTE:  volumes, rates, stop_times and repeats must have either all the same length or a length of one.

    """

    # Check input arguments
    nvols, nrate = len(volume), len(rate)
    nst, nrep = len(duration), len(repeat)
    
    if nvols != nrate or nvols!= nst or nvols!= nrep:
        print(f'pumptools.make_sequence > Lengths of your arrays do not match : volume:{nvols}, rate:{nrate}, duration:{nst}, repeat:{nrep} . They should be equal ') 
        raise ValueError
    
    n_in_cycle = len(cycle_kind)
    n_steps = n_in_cycle*np.sum(repeat)        # Should give us the correct number of steps
    step_list = np.arange(0, n_steps).astype(int)
    step_vol  = []
    step_rate = []
    step_dur = []
    step_type = []
    step_cycle = []
    step_repeat = []

    # Creating list of steps
    for cyc_no in range(nvols):
        step_type.extend(list(cycle_kind)*repeat[cyc_no])
        step_rate.extend([rate[cyc_no]]*n_in_cycle*repeat[cyc_no])
        step_dur.extend([duration[cyc_no]]*n_in_cycle*repeat[cyc_no])
        step_cycle.extend([cyc_no]*n_in_cycle*repeat[cyc_no])
        step_repeat.extend(np.repeat(np.arange(0,repeat[cyc_no]).astype(int), repeats=len(cycle_kind)))

        if not center or (cycle_kind != 'i0w0' and cycle_kind != 'w0i0'): # Basically if we do not ask to center or if we have an "uncentered" cycle (i.e. not a cycle)
            step_vol.extend([volume[cyc_no]]*n_in_cycle*repeat[cyc_no])
        else:
            v_half, v_full = volume[cyc_no]/2, volume[cyc_no]
            v_list = [v_full]*n_in_cycle*repeat[cyc_no]
            v_list[0] = v_half
            v_list[-2] = v_half
            step_vol.extend(v_list)
    
    sequence = pd.DataFrame(data={'cycle': step_cycle, 'repeat': step_repeat,
                                  'type':step_type, 'volume':step_vol, 'rate':step_rate,  
                                  'duration':step_dur}, index=step_list)  
    
    # Validate duration : 
    io_steps = (sequence['type'] == 'i') | (sequence['type'] == 'w')
    sequence.loc[io_steps, 'duration'] = 60*sequence.loc[io_steps, 'volume']/sequence.loc[io_steps, 'rate']
    sequence['time'] = np.cumsum(sequence['duration'] + 1.5)

    print('---------- PUMP SEQUENCE -----------')
    print(sequence)
    
    return sequence

##########################################################################################
######## TESTS ###########################################################################

def advanced_test(port='COM3', reverse=False):
    print(f'Testing syringe pump on port {port} : regulation')
    print('Check that no syringe is connected to the pump.')
    print('Press +/- on your keyboard to modify pressure (target is 10.0)') 

    def fake_pressure_signal(p_measure:shared_var, max_time=50):
        import keyboard
        t0 = time.time()   
        print('Press +/- to increase/decrease pressure')
        while time.time() - t0 < max_time:
            pnow = p_measure.get()

            if keyboard.read_key() == "+":
                p_measure.set(pnow + 1)
                time.sleep(0.1)   
            elif keyboard.read_key() == '-':
                p_measure.set(pnow - 1)
                time.sleep(0.1)
        return 0 

    p_measure = shared_var(0.0)
    maxtime = 50
    mypump = Pump(port=port, infuse_rate=500, withdraw_rate=500, ini_volume=5000)    
    fpt = threading.Thread(target=fake_pressure_signal, kwargs={'p_measure':p_measure, 'max_time':maxtime})
    reg = threading.Thread(target=regulate, kwargs={'pump':mypump, 'p_measure':p_measure, 'p_target':10.0, 
                                                    'max_time':maxtime, 'reverse':reverse, 'absolute_tolerance':1})
    fpt.start()
    reg.start()
    time.sleep(maxtime)
    reg.join()
    fpt.join()

def basic_test(port='COM3'):
    print(f'Testing syringe pump on port {port} : simple sequence')
    print('Check that no syringe is connected to the pump.')

    mypump = Pump(port=port)
    sequence = make_sequence(cycle_kind='i0w0', volume=[50], rate=[500], repeat=[4], duration=[2])
    run_sequence(pump=mypump, sequence=sequence)
    

###############################################################################################
###############################################################################################

if __name__ == '__main__':
    basic_test()




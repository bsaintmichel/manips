# fluigenttools.py : Some convenience functions to easily apply
# pressure ramps and
# (Brice)

# NOTE : for the current model we have

import Fluigent.SDK as fluigent
import numpy as np
import pandas as pd
import time

def init():
    """ INIT() : Initialises the Fluigent devices"""
    fgt_error = fluigent.fgt_init()
    return fgt_error

def close():
    """ CLOSE() : Closes the Fluigent devices"""
    fgt_error = fluigent.fgt_close()
    return fgt_error

def make_ramp(low=0, high=0, nsteps=1, tstep=1, repeats=2,
              log_steps=False, reverse=False, symmetric=False):
    """ MAKE_RAMP() : Creates a pressure ramp for you to play with 
    
    ARGS
    ----
    * low [int, default 0] : the low pressure you want to reach (in PASCALS)
    * high [int, default 0] : the high pressure you want to reach (in PASCALS)
    * nsteps [int, default 0] : the number of steps between low and high you want to perform
    * tstep [int, default 1] : the time spent on each step (in s)
    * repeats [int, default 1] : the number of repeats of the pressure steps you want to perform
    * log_steps [bool, default False] : if you want to do logarithmic steps instead of linear
    * reverse [bool, default False] : if you want to start from high pressures and go to low ones 
    * symmetric [bool, default False] : adds a reverse ramp at the end of your ramp
     """

    high/= 100  # Convert to mbar (fluigent units)
    low/= 100   # Convert to mbar (fluigent units)

    if log_steps and (low <= 0):
        raise ValueError('fluigenttools.make_ramp >> Low pressure cannot be <= 0 in log mode ...')
    
    # Design p_ramp per se
    if not log_steps:
        p_ramp = np.linspace(low, high, nsteps).astype(int)
    else:
        p_ramp = np.logspace(np.log10(low), np.log10(high), nsteps).astype(int)
    if reverse:
        p_ramp = p_ramp[::-1]
    if symmetric:
        p_ramp = np.hstack((p_ramp, p_ramp[-2::-1]))
   
    # Dealing with repeats (and ditching the duplicates)
    if repeats > 1:
        last_p_ramp = p_ramp
        if symmetric:
            first_p_ramps = p_ramp[:-1]
        else: 
            first_p_ramps = p_ramp
        
        p_ramp = np.tile(first_p_ramps, repeats-1)
        p_ramp = np.hstack((p_ramp, last_p_ramp))

    step = np.arange(len(p_ramp))
    stime = (1+step)*tstep 

    df = pd.DataFrame(data={'step':step, 'pressure':p_ramp, 'time':stime}, index=step) # The df just feels naked without a "step" column ...*

    print('---------- FLUIGENT SEQUENCE -----------')
    print(df)
    print('----------------------------------------')

    return df

def run_ramp(pressure_index=0, ramp=pd.DataFrame(), acq_rate=10, save_folder='.', 
             switch_off_at_end=False, verbose=False, run_event=None, stop_time=None):
    """RUN_RAMP() : Runs a pressure ramp on the Fluigent controller. The function
    also records the (measured ?) pressure from the device while it tries to apply
    the pressure you ask. So no big surprises normally.
    
    ARGS
    -----
    * pressure_index [int, default 0] : the "channel" with which you want to work 
    * ramp [pd.DataFrame, default empty df] : the ramp of pressure you want to work with.
    You can use make_ramp to create your ramp, or just specify a df with "pressure", "time" columns.
    * acq_rate [float, default 5] : the number of pressure measurements you want to take per second
    * save_folder [str, default '.'] : where you want your nice 'fluigent_log.txt' to be saved
    * switch_off_at_end [bool, default False] : if you want to put p to 0 at the end of the ramp
    * verbose [bool, default False] : if you want the program to print every step in the standard output 
    """
    step = 0
    acq = 0
    pmeas = 0
    timestamp = 0
    p = ramp.iloc[0]['pressure']
    no_error = fluigent.fgt_ERROR(0) # Basically "no error"
    fgt_error = no_error

    with open(save_folder + '/fluigent_log.txt', 'w') as log_file:
        log_file.write('step,texp,tint,p_target,p_measured\n')

    if stop_time == None:
        stop_time = np.max(ramp['time'])

    t0 = time.time()
    fluigent.fgt_set_pressure(pressure_index=pressure_index, pressure=ramp.iloc[0]['pressure'])
    if verbose:
        print(f'fluigenttools.run_ramp >> Step n°{step}, p={p} mbar')
    
    while time.time() - t0 <= stop_time and step < len(ramp):
        t_now = time.time()

        if run_event is not None and not run_event.is_set():    # If main thread has told you to die, basically
            print('fluigenttools.run_ramp() >> Aborted.')
            break

        if t_now - t0 > ramp.iloc[step]['time'] and step < len(ramp) and t_now - t0 < stop_time:
            step += 1
            p = ramp.iloc[step]['pressure']
            fgt_error = fluigent.fgt_set_pressure(pressure_index=pressure_index, pressure=p)
            print(f'fluigenttools.run_ramp >> Step n°{step}, p={p} mbar')

        if (t_now - t0)*acq_rate > acq:
            acq += 1
            (fgt_error, pmeas,timestamp) = fluigent.fgt_get_pressure(pressure_index=pressure_index, 
                                                                     include_timestamp=True, get_error=True)
            with open(save_folder + '/fluigent_log.txt', 'a') as log_file:
                log_file.write(f'{step},{t_now},{timestamp},{100*ramp.iloc[step]["pressure"]:.2f},{100*pmeas:.2f}\n')

        if fgt_error != no_error:
            print(f'fluigenttools.run_ramp >> Channel {pressure_index} encountered {fgt_error} !')
            break
        
    if switch_off_at_end:
        print(' ')
        fluigent.fgt_set_pressure(pressure_index=pressure_index, pressure=0)

    print('fluigenttools.run_ramp >> Ramp complete')
    return 0


###############################################################
# A little test if you want to run the thing directly from here
###############################################################

if __name__ == '__main__':
    init()
    ramp = make_ramp(low=10,high=100,nsteps=10, tstep=1, repeats=1, symmetric=True)
    run_ramp(ramp=ramp, acq_rate=3, switch_off_at_end=True, verbose=True)
    close()
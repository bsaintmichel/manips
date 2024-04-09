# Manips 

Brice Saint-Michel : `bsaintmichel` if you look for me on Gmail

## What does this do ?

Basically, it calls a bunch of Python scripts to allow you to locally use : 
- a Basler or Allied Vision camera
- a Harvard PhD Ultra Pump
- a MXP 5010 / 5100 sensor coupled to an Arduino
- a Fluigent pressure controller (this part of the script is a bit out of date)

## Some prerequisites  

- pypylon and (recommended) the Pylon SDK suite.

    ```
    PS C:\Users\ADMIN> pip install pypylon
    ```

    I would make sure during the installation of the Pylon SDK that you have selected the drivers for your type of camera (GigE or USB3).

- Vimba X and `vmbpy`. For the latter, the `.whl` file you need to install is in the `/utils` folder. Go to the `/utils` folder using command prompt and run :

    ```
    PS [...]/bubblemanip/utils> pip install vmbpy-1.0.4-py3-none-any.whl
    ```

    The current `.whl` file should work for any architecture (maybe except the more recent Mac M1-M3 non x86 chips). Otherwise you can find the most recent version of the software on [vmbpy's Github releases](https://github.com/alliedvision/VmbPy/releases)

- The `serial` module, but it is called `pyserial` when you want to install it with `pip` : 

    ```
    PS C:\Users\ADMIN> pip install pyserial
    ```

    Both the syringe pump and the Arduino sensor work with the `serial` module.

- The `Fluigent.SDK` module. I have also put a version of it in the `/utils` folder, and you can install it with : 

    ```
    PS [...]/bubblemanip/utils> pip install fluigent_sdk-23.0.0.zip
    ```

    Otherwise, once again you can find it on [Fluigent's Github release pages](https://github.com/Fluigent/fgt-SDK/releases/tag/23.0.0). Download and open the `.zip` file, go to the `Python` subfolder and extract the second `.zip` file in there. That one you can install with `pip`.

- The `opencv` module. I am using it to create viewing windows that are a bit more responsive than Matplotlib. They can also be called from a side thread.
    ```
    PS C:\Users\ADMIN> pip install opencv-python
    ```

- The `av` module used to make videos from image lists : 
    ```
    PS C:\Users\ADMIN> pip install av
    ```

## Detailed contents

### Baslercam and Vimbacam

I wrote these programmes so that the syntax to call them is the same regardless of the camera : 

- `init()` allows you to initialise the camera. The function returns the first camera (Basler) or the camera n° you have chosen (default first camera, Vimba). Quite a few options are possible (change width, height, set exposure time, binning, ...)
- `acquire()` allows you to capture an image sequence. It opens a live imaging window, and saves images:
  * either at fixed time intervals if you speficy `dt` and `max_time`
  * either at the selected times if you  specify `t`
  * or following certain events if you specify `extsave` and `max_time`. Objects of type Extsave are rather simple, they have a `.lock` attribute allowing them to only be handled by one thread, and a `.save` attribute indicating whether an image needs to be saved. Once set to `True`, the `acquire` programme will save an image and force the value of `.save` to `False` (and you have to set it to `True` again to trigger a new image acquisition).
  
  The programme also logs the timestamps and some info about the images in a `camera_log.txt` file.
- `make_video()` : this little helper guy will make a high-quality video out of the list of images you have. __It can also delete the image files if you want__, please be careful with these options.
- `make_logtimes()` : allows you to produce a time array with sample times arranged logarithmically, which can be later used in `acquire()`.

### Pump

I have defined a `Pump` class in there, so to connect to your `Pump`, you can just say :

```
mypump = Pump(port='COM5')
```
The main functions you should be using are :

- `make_sequence()` : allows you to create injection/withdrawal sequences with given volumes, rates, number of repeats, ...
- `run_sequence()` : runs the injection/withdrawal sequences designed with `make_sequence()`, and logs the result in a `pump_log.txt` file.
- `regulate` : a _poor man's_ attempt at regulating a _pressure_ (from an external measurement) around a _target_ using the syringe : basically, if we are above target, we withdraw, and if we are under target, we inject. NOTE: if you want the reverse behaviour, there is an option for that.

### Sensor

Same as `Pump`, I wrote a class for it.
```
mysensor = Sensor(port='COM5')
```

You will be interested in : 

- `acquire()` : starts an acquisition, and logs the results in `sensor_log.txt`

## FAQ 

### Is there no Pytango ?

Nope, not here. Everything in there _may_ be wrapped in Pytango routines in the future, but for now I am not doing that. 

### The `pip` command is not recognised (on my Windows machine)

Have you added the Python path to your environment variables ? [Check this guide](https://www.educative.io/answers/how-to-add-python-to-path-variable-in-windows). 

### How do I know which COM port corresponds to my serial device ?

If you have plugged in your pump and arduino card using USB, you can check what `COM` port they correspond to on the computer either with the device manager (_gestionnaire de périphériques_) and the _ports COM_ tab, or using a third-party software such as `USBdeview`.

### How do I quickly test the devices individually ? 

There is a tiny bit of code at the end of each `.py` file. They start with :
```
if __name__ == '__main__':
    [...]
```
It means that if you directly run these files, they will start the code inside the `if` condition. I have set up some basic tests in there ; for `baslercam`, `vimbacam` and `pump`, you can modify the code in there to do an `advanced_test` to test running acquisitions with threads and interaction with external inputs (e.g. keyboard presses).

### How do I call the functions / variables of your scripts from the other Python files ?

Python is easy with you. Check where you run your Python scripts from. Say you want to run `toto.py` located in `/bubblemanip/examples` :

```
PS [...]/bubblemanip> python ./examples/toto.py
``` 

We don't care so much where `toto.py` is, what is important is the folder you work with in your command line prompt (here, `/bubblemanip`). So if you want to import, e.g. `fluigent.py` in your `toto.py` file, you just need to write :

```
import fluigent as fg
```

If `fluigent.py` were to be located in `/utils`, you could import it using :

```
import utils.fluigent as fg
```

### How do you run multiple functions at once ?

#### Basic thread usage

You can run multiple programmes at once using `Threads`, from the [`threading` package](https://docs.python.org/fr/3/library/threading.html). Say you have a function `myfunction_1` that takes some time to complete, and you want to run in parallel to `myfunction_2` which also takes some time to complete. Calling them sequentially will not do what you want :

```
import time 

def myfunction1(arg1=1, arg2=2):
    t0 = time.time()
    while time.time() - t0 < 10:
        time.sleep(0.1)
    return arg1, arg2

def myfunction2(arg=None):
    t0 = time.time()
    while time.time() - t0 < 5:
        time.sleep(0.1)
    return arg

myfunction_1(arg1=12)
myfunction_2(arg=[7])
```

You can instead create two `Threads` based on these functions. Creating a `Thread` is not too complicated, you just need to specify its `target` (the function you want to run) and pass its arguments with the `kwargs` additional argument (`kwargs` stands for keyword arguments) in the form of a dictionary. It looks like this :

```
    import threading

    thread_1 = threading.Thread(target=myfunction_1, 
                                kwargs={'arg1':12})
    thread_2 = threading.Thread(target=myfunction_2, 
                                kwargs={'arg':[7]})
```

You can then `start` these threads, and you should, at a later point, wait for them to finish and `join` the main programme :

``` 
    thread_1.start()
    thread_2.start()
    [either nothing or 'in the meantime' code]
    thread_2.join()
    thread_1.join()
    ['later on' code]
```

The main loop will wait for the two threads to finish before running the `later on` code. 

#### Allowing threads to be interrupted by the keyboard 

If you want to be able to stop these threads by pressing `Ctrl + C`, you need to include an `Event` as an argument in your threads. You then have to slightly tweak the definition of your functions ; the syntax I use is : 

```
import time 

def myfunction1(arg1=1, arg2=2, run_event=None):
    t0 = time.time()
    while time.time() - t0 < 10:
        if run_event is not None and not run_event.is_set():
            break
        time.sleep(0.1)
    return arg1, arg2

def myfunction2(arg=None):
    t0 = time.time()
    while time.time() - t0 < 5:
        if run_event is not None and not run_event.is_set():
            break
        time.sleep(0.1)
    return arg
```

And your main code has to be changed to try to intercept the `Ctrl + C` command to reset the `Event`. We can do this by using a `try ... except`  : 

```
    import threading

    run_event = threading.Event()
    run_event.set() # When it is no longer set, the threads will end

    thread_1 = threading.Thread(target=myfunction_1, 
                                kwargs={'arg1':12, 'run_event':})
    thread_2 = threading.Thread(target=myfunction_2, 
                                kwargs={'arg':[7], 'run_event':})

    try:
        thread_1.start()
        thread_2.start()
        [either nothing or 'in the meantime' code]
        thread_2.join()
        thread_1.join()
        ['later on' code]

    except KeyboardInterrupt:
        run_event.clear()
```

#### Running code after a keyboard interruption

If your functions are supposed to return something, make sure that they won't crash if they have to return early ! Also, you should know that in case you press `Ctrl + C`, your `later on` code will not be run. If you still want to run your later on code, you should add a `finally` statement : 

``` 
    [...]
    except KeyboardInterrupt:
        run_event.clear()

    finally:
        ['later on' code]
```


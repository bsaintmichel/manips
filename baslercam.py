import os
import time
import glob
import av
import cv2
import threading

import numpy as np
from pypylon import pylon
from PIL import Image
from scipy.ndimage import laplace

to_rgb = {'Mono8':cv2.COLOR_GRAY2RGB, 'BGR8':cv2.COLOR_BGR2RGB}

class save:
    """ A simple class to instruct the camera to acquire images ; 
    the camera can then let the object know that the image has been
    acquired """
    def __init__(self, t=None, t0=time.time()):
        self.lock = threading.Lock()
        self.save = False
        self.t0 = t0
        self.t = t
        self.index = 0

    def set_t0(self, t0=time.time()):
        with self.lock:
            self.t0 = t0

    def check_time(self):
        if self.t is not None:
            if time.time() - self.t0 > self.t[self.index]:
                self.set_trigger()

    def set_trigger(self):
        with self.lock:
            self.save = True

    def get_trigger(self):
        return self.save
    
    def complete(self):
        with self.lock:
            self.save = False
            self.index += 1

    def get_index(self):
        return self.index



def get_imgprops(data:np.ndarray, roi=None):
    """ A function that builds some kind of arbitrary
    sharpness value from a numpy array (treated as an image).
    Based on statistics on the normed gradient of the image
    (basically sharpness is the average of the square of the image gradient)
    
    ARGS
    -----
    - data : your image in np.ndarray format
    - roi : [top, down, left, right] : the region of interest on which to focus"""

    if data.ndim == 3:
        data = data[:,:,1]

    if roi is None:
        h, w = data.shape
        roi = [2*h//5,(3*h)//5, 2*w//5, (3*w)//5]
    data = data[roi[0]:roi[1], roi[2]:roi[3]]

    lum_now = np.mean(data)
    norm_grad = np.mean(np.abs(laplace(data - lum_now))**2) # Dividing by the std is not good since out of focus --> smaller std.

    return lum_now, norm_grad

def init(width=None, height=None, exposure='auto', binning=1) -> pylon.InstantCamera:
    """ Init : 
    
    ARGS
    ----
    * width : Image width. Will throw an error if above MaxWidth
    * height : Image height. Will throw an error if above MaxHeight
    * exposure [str or 'auto'] """


    # Basler cameras work with Software Trigger, no time to see if I can make
    # them work differently
    cam = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
    cam.RegisterConfiguration(pylon.SoftwareTriggerConfiguration(), 
                                    pylon.RegistrationMode_ReplaceAll,
                                    pylon.Cleanup_Delete) 
    
    
    cam.Open()
    cam.UserSetSelector.Value = cam.UserSetDefault.Value # use default settings
    cam.UserSetLoad.Execute()

    # Binning
    cam.BinningHorizontal.Value = binning
    cam.BinningVertical.Value = binning

    # Setting Height and Width
    maxwidth = cam.WidthMax.Value
    maxheight = cam.HeightMax.Value
    
    if not height: height = maxheight
    elif height // binning < maxheight:
        height = 8*(height // (8*binning))
        cam.Height.Value = height
        cam.OffsetY.Value = int((maxheight - height)/2)
    if not width: width = maxwidth
    elif height // binning < maxwidth:
        width = 8*(width // (8*binning))
        cam.Width.Value = height
        cam.OffsetX.Value = int((maxwidth - width)/2)

    # Not sure about this, but it works so I'll leave them
    cam.MaxNumBuffer = 10 

    if exposure == 'auto':
        cam.AutoTargetBrightness.Value = 0.5
        cam.AutoFunctionROISelector.Value = "ROI1"
        cam.AutoFunctionROIUseBrightness.Value = True
        cam.ExposureAuto.Value = "Continuous"
        cam.AutoExposureTimeUpperLimit.Value = 100000
    else:
        cam.ExposureAuto.Value = 'Off'
        cam.ExposureTime.Value = exposure

    # Change (if applicable) pixel format to BGR8 to display on OpenCV natively
    if cam.PixelFormat.Value == 'RGB8':
        cam.PixelFormat.Value = 'BGR8'

    print(f'baslercam.init > {cam.DeviceModelName.Value} ({width} x {height}) with {cam.PixelFormat.Value} pixel format')

    cam.Close()
    
    return cam


def acquire(cam:pylon.InstantCamera, save_folder='.', dt=None, max_time=None,
                   t=None, abort_thread=None, extsave=None):
    
    """ ACQUIRE_FRAMES () : Runs an acquisition and saves images 
    
    ARGS
    -----
    * cam [camera] : your camera object
    * dt [float] : (to be used with max_time) the time interval between two images you are looking for
    * max_time [float] : (to be used with max_time) the total time of your acquisition
    * t [list or np.ndarray] : the list of times at which you want to snap images (if you don't want a constant frame rate)
    * save_folder [default '.'] : where you want to save the images
    * abort_thread [threading.Event type] : the "kill switch" from main process if you want to run this as a thread 
    * save_event [class save_event from this file] : a 'flag' that you can set in another process to instruct the camera to save from time to time
    
    NOTE: now, by default, we save the results as a video. If you don't want that
    please set the `saveasvideo` option to `False`.""" 
    
    # Write header file
    headerstr = f'{"no":7s}\t{"texp":8s}\t{"tlocal":15s}\t{"expos":7s}\t{"lumi":7s}\t{"sharp":7s}'
    print(headerstr)
    with open(save_folder + '/camera_log.txt', 'w') as logfile:
        logfile.write(headerstr.replace('\t', ',') + '\n')

    # Deal with t's, delta t's, etc.
    # I use the `save` class which basically instructs the programme
    # to save images following a flag being set in there
    if max_time is not None and dt is not None:
        t_snap = np.arange(0,max_time+dt,dt)
        mysave = save(t=t_snap)
    elif t is not None:
        t_snap = np.array(t_snap)
        max_time = t_snap[-1] + 1
        mysave = save(t=t_snap)
    elif max_time is not None and extsave is not None:
        mysave = extsave
    else:
        raise ValueError('acquire_frames > You must specify [a list of times with `t`] / [a `max_time` and a `dt`] / [a `max_time` and an external save variable]')


    # The try / finally will allow us to finish the video 
    # even if there is an issue somewhere else in the programme     
    try: 
        
        cv2.namedWindow('Live Feed')
        cam.StartGrabbing(pylon.GrabStrategy_LatestImages)

        t0 = time.time()
        mysave.set_t0(t0=t0)

        while time.time() - t0 < max_time:

            if abort_thread is not None and not abort_thread.is_set():
                print('baslercam.acquire > Aborted.')
                break

            # Grabbing image
            if cam.WaitForFrameTriggerReady(200, pylon.TimeoutHandling_ThrowException):
                cam.ExecuteSoftwareTrigger()
            grabResult = cam.RetrieveResult(500, pylon.TimeoutHandling_ThrowException) 

            # If grab succeeded, see what we do with the image
            if grabResult.GrabSucceeded():
                frame = grabResult.Array
                timestamp = grabResult.TimeStamp
                img_lum, img_sharp = get_imgprops(frame.astype(np.int32))
                exposure = cam.ExposureTime.Value

            cv2.imshow('Live Feed', frame)
            cv2.waitKey(1)    # Enforces display & waits for 1 ms. Somehow programme crashes at the end for larger values...

            # If we have specified times for our `save` object, check if these times may 
            # trigger frame save
            mysave.check_time()

            # Save if we need to
            if mysave.get_trigger():
                
                saveidx = mysave.get_index()

                # Convert and save frame
                if cam.PixelFormat.Value != 'RGB8':
                    rgbframe = cv2.cvtColor(frame, to_rgb[cam.PixelFormat.Value])       # Deal with nonstandard pixel formats
                pilimg = Image.fromarray(rgbframe, mode='RGB')
                pilimg.save(save_folder + f'/img_{saveidx:06d}.tif')

                # # Write about the saved frame 
                datastr = f'{saveidx:5d}\t{time.time()-t0:8.2f}\t{timestamp:12d}\t{exposure:7.1f}\t{img_lum:5.1f}\t{img_sharp:6.2f}'
                with open(save_folder + '/camera_log.txt', 'a') as logfile:
                    logfile.write(datastr.replace('\t', ',') + '\n')
                print(datastr)

                mysave.complete()

    # Stop acquisition if keyboard interrupt (this time if this function is directly called)
    except KeyboardInterrupt:
        print('acquire > Keyboard Interruption ...')

    finally:
        cv2.destroyWindow('Live Feed')
        cam.Close()
        print('baslercam.acquire >> Camera Acquisition Complete')

############################# UTILITIES ###################################################################
###########################################################################################################

def make_video(save_folder, expr='*.tif*', cleanup=False):
        """ Makes a video from a list of .TIFF files 
        
        ARGS
        -----
        * save_folder : where the TIFF /etc. files are
        * expr [default '*.tif*'] : what to look for in the folder to make the video
        * cleanup [default False] : delete the original images after video is successfully made

        NOTE : The videos are made using libx265 and yuv444p pixel space so as to not lose color info
        """

        # Initialise video ... (need a test frame)
        imgurls = glob.glob(save_folder + '/' + expr)
        test_frame = Image.open(imgurls[0])
        
        container = av.open(save_folder + '/exp.mp4', mode='w')
        stream = container.add_stream("libx265", rate=24, options={'crf':'13', 'x265-params':'log-level=error'})
        stream.pix_fmt = "yuv444p"
        stream.height, stream.width = np.shape(test_frame)[:2]

        for no, imgurl in enumerate(imgurls):
            frame = av.VideoFrame.from_image(Image.open(imgurl))
            for packet in stream.encode(frame):
                container.mux(packet)
            if no % 100 == 0:
                print(f'vimbacam.make_video > {no} / {len(imgurls)} frames', end='\r')

        # Finish video eventually
        for packet in stream.encode():
            container.mux(packet)
        container.close()
        print('vimbacam.make_video > Finished encoding video.')

        if cleanup:
            print(f'vimbacam.make_video > !!! NOW REMOVING ORIGINAL IMAGES in {save_folder} !!! \n\n')
            time.sleep(2)
            for imgurl in imgurls:
                os.remove(imgurl)


def make_logtimes(dt0=0.5, tmax=3600, pts_per_decade=20):
    """ A function that creates a logarithmic time scale
    for video acquisitions at non-constant frame rate.
    
    ARGS
    ------
    * dt0 [float] : your delta t between frames initially.
    * tmax [float] : the maximum time of your experiment (can be taken from stop_time !).
    * pts_per_decade [int] : the number of points you want to take before multiplying delta t by 10.
    """

    alpha = np.log(10)/pts_per_decade
    N = int(1/alpha*np.log(1+tmax/dt0*(np.exp(alpha)-1)))
    dtmax = dt0*np.exp(alpha*N)
    dt_scale = np.logspace(np.log10(dt0), np.log10(dtmax), N)
    T_total = np.sum(dt_scale)
    print(f'make_logspace > N = {N:.3f} frames, total time = {T_total:.2f} s, alpha = {alpha:.2f}, dtmax = {dtmax:.3f}')
    return np.logspace(np.log10(dt0), np.log10(dtmax), N)
    

######################### TESTS #############################
#############################################################

def advanced_test():
    """ An advanced test for pypylon : press 'Enter' to save images. 
    """
        
    def keyboard_trig(extsave:save, max_time=10):
        """ A keyboard based trigger : converts a 'Enter' key 
        into a signal to acquire an image """
        import keyboard
        t0 = time.time()
        while time.time() - t0 <= max_time:
            if keyboard.read_key() == "enter":
                extsave.set_trigger()
                time.sleep(0.1)
    
    print('Testing the Basler Camera : press Enter to save images')
    cam = init()
    mysave = save()
    maxtime = 20

    ktt = threading.Thread(target=keyboard_trig, kwargs={'extsave':mysave, 'max_time':maxtime})
    acq = threading.Thread(target=acquire, kwargs={'cam':cam, 'extsave':mysave, 'max_time':maxtime})

    ktt.start()
    acq.start()
    time.sleep(maxtime)
    ktt.join()
    acq.join()

def simple_test():
    """ A simple test for pypylon : will acquire images for 10 seconds and save five of them"""
    print('Testing the Basler Camera')
    cam = init()
    acquire(cam, dt=2, max_time=10)


################################################################
################################################################

if __name__ == '__main__':
    simple_test()
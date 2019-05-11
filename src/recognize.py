"""
    This file deals with the detection of commercials in a given video
"""
from dejavu.recognize import FileRecognizer, DataRecognizer
import os
import timeFunc
from constants import *
import ffmpeg
from dejavu import Dejavu, decoder
import numpy as np
from fileHandler import LabelsFile, DatabaseFile
import sys
import mimetypes
import time
import pprint
import pusher
import copy
import thread


class Recognize(object):
    
    """
        This class runs the audio fingerprinting algorithm to find matches of commercials in the audio.
    """

    def __init__(self, video_name, sourceid=None, region=None, programname=None, programid=None, scheduleid=None):
        
        """
           Takes the video name. Creates a Dejavu object.
           Also obtains the duration and number of frames in the video.
        """
        
        self.video_name = video_name
        self.djv = Dejavu(CONFIG)
		self.sourceid = sourceid
		self.region= region
		self.programname = programname
		self.programid = programid
		self.scheduleid = scheduleid
        
        self.frames, self.Fs, hash_val = decoder.read_raw_from_fd(sys.stdin, seconds=VIDEO_SPAN*2)

        self.frames = self.frames[0] #Since we always create single channel audio
        self.duration = int(self.frames.shape[0] / (self.Fs*1.0)) #Duration of the entire video in seconds


    def push_notify_with_repeat (self, song):
        for i in range (5):
            song["AlertCount"]=i+1
            self.push_notify (song)
            time.sleep (3*60)

    def push_notify (self, song):
		pusher_client = pusher.Pusher(
	  		app_id=os.environ.get('PUSHER_APP_ID', None),
	  		key=os.environ.get('PUSHER_KEY', None),
	  		secret=os.environ.get('PUSHER_SECRET', None)
	  		ssl=True
	)
   
	if song['external_id'] is None:
	    pusher_channel="NonCampaignAds"
	else:
	    pusher_channel="CampaignAds"

	info={ "DetectSystemAdId": song['song_id'],
		"Name": song['song_name'],
		"AdId": song['external_id']  }
	info["SourceID"] = self.sourceid
	info["RegionID"] = self.region
	info["ProgramName"] = self.programname
	info["ProgramID"] = self.programid 
	info["ScheduleID"] = self.scheduleid 
	if song["AlertCount"] is not None:
	    info["AlertCount"] = song["AlertCount"]
	pusher_client.trigger(pusher_channel, 'ad_identified', info)

#VIDEO_SPAN =How much to take to analyze audio, defined in constants, default 5 seconds
        
    def find_commercial(self, start, span=VIDEO_SPAN):
        
        """
            Uses audio fingerprinting to detect known commercials
            Returns:
                If commercial is detected it returns the following:
                    [end_time, [actual_start of commercial, duration of commercial]]
                If no commercial is found
                    [start(the value that was passed), []]
        """
        song = self.djv.recognize(DataRecognizer, [self.frames]) #Call dejavu to audio fingerprint it and find a match
        
        if song is None:
            #No match was found in the db
            return None
            
        if song[DJV_CONFIDENCE] >= CONFIDENCE_THRESH:
            #A high confidence match was found
            pprint.PrettyPrinter(indent=4).pprint (song)
            if song[DJV_OFFSET] < 0:
                #Offset can never be greater than duration of detected commercial
				print "Negative offset, returning..."
				return None
            
            num_seconds=int (song['num_frames']/self.Fs)
            song['num_seconds']=num_seconds
            remaining_seconds=int (song['num_frames']/self.Fs - song['offset_seconds'])
            song['remaining_seconds']= remaining_seconds

            return song
        else:
            #A match was found, but not a confident match
            return None
            
    def recognize(self):       
    
    i = 0  # Seconds into the data (?)
	found_commercials = []
    must_skip_seconds=0
	while True:
	    read_tries=0
	    duration=0
	    while True:
		# must_skip_seconds contains the seconds remaining from the previously
		# detected clip, which we skip here to avoid a 2nd detection.
		wanted_seconds=max (must_skip_seconds, VIDEO_SPAN-duration+1)
		#print "Wanted seconds now: ",
		#print wanted_seconds
		more_data = decoder.read_raw_from_fd(sys.stdin, seconds=wanted_seconds)
		can_skip_seconds=int (len (more_data[0][0])/self.Fs)
		#print "can_skip_seconds now: ",
		#print can_skip_seconds
		if must_skip_seconds>0:
			remove_seconds=min (can_skip_seconds, must_skip_seconds)
			more_data[0][0]=more_data[0][0][remove_seconds*self.Fs:]
			must_skip_seconds=must_skip_seconds-remove_seconds
			i=i+must_skip_seconds-remove_seconds


		if more_data is None or len (more_data[0][0])==0: #No data read
		    read_tries=read_tries+1
		    if read_tries>=5: # No data for 5 seconds, we're done
			print "No data in 5 seconds"
			time.sleep (1)
			break
		else:
	        	self.frames = np.append (self.frames,more_data[0][0])
            		duration= int(self.frames.shape[0] / (self.Fs*1.0))
			if duration>=VIDEO_SPAN: # Enough buffer for now
			    break

            if read_tries>=5:  # Get out of the outter loop
		print "Exiting outer due to read_tries..."
		break

            sys.stdout.flush()
            song = self.find_commercial(0)
            
            if song:
		print "We should have something!"
		print song
		print "And the song name: ",
		print DJV_SONG_NAME
		name=song[DJV_SONG_NAME] 
		found_commercials.append (song)
		self.djv.insert_detection_log_entry (song['song_id'], song['song_name'], song[DJV_OFFSET],
			self.programname, song['external_id'], self.region, self.sourceid,
		 	self.programid, self.scheduleid)
                songcopy=copy.deepcopy(song)
#		self.push_notify (songcopy)
                thread.start_new_thread( self.push_notify_with_repeat, (songcopy, ) )
		must_skip_seconds = song['remaining_seconds']
                
            i=i+duration
	    #self.frames=self.frames[44100:]
	    self.frames=self.frames[0:0]
            if i%10 == 0: 
		print "\nElapsed seconds: "+str (i)+"\n"

               
    def __del__(self):
        pass
                


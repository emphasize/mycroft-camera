# Copyright 2021 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import cec
from time import sleep

from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_handler
from mycroft.skills import skill_api_method


class CameraSkill(MycroftSkill):
    """
    Camera Skill Class
    """

    def __init__(self):
        super(CameraSkill, self).__init__("CameraSkill")
        self.camera_mode = None
        self.cams = self.config_core.get("cams", {})

        self.save_folder = os.path.expanduser("~/Pictures")
        if not os.path.isdir(self.save_folder):
            os.makedirs(self.save_folder)

    def initialize(self):
        """Perform any initial setup."""
        # Register Camera GUI Events
        self.gui.register_handler("CameraSkill.ViewPortStatus", self.handle_camera_status)
        self.gui.register_handler("CameraSkill.EndProcess", self.handle_camera_completed)

        # Register Bus Events
        self.bus.on("skill.camera.showcam", self.handle_stream)
        # register cam names for adapt
        for word in self.cams.keys():
            self.register_vocabulary(word, "location")
        self.setup_cec()

    def setup_cec(self):
        cecconfig = cec.libcec_configuration()
        cecconfig.strDeviceName = "MycroftCEC"
        cecconfig.bActivateSource = 0
        cecconfig.deviceTypes.Add(cec.CEC_DEVICE_TYPE_RECORDING_DEVICE)
        cecconfig.clientVersion = cec.LIBCEC_VERSION_CURRENT
        # Create, Detect, and Open adapter
        self.remote = cec.ICECAdapter.Create(cecconfig)
        adapters = self.remote.DetectAdapters()
        for i, adapter in enumerate(adapters):
            self.log.debug(f"CEC adapter {i+1} port:{adapter.strComName} \
                           vendor: {hex(adapter.iVendorId)} \
                           product: {hex(adapter.iProductId)} ")
        if len(adapters) == 0:
            self.log.warning("could not find any CEC adapters!")
            self.speak_dialog("display.not.available")
            self.display = False
        else:
            self.log.debug(
                "found %d CEC adapters, attempting to open first adapter..." % len(adapters))
            self.display = True
            if self.remote.Open(adapters[0].strComName):
                self.log.info("CEC adapter opened")
            else:
                self.log.error("unable to open CEC adapter!")
            addresses = self.remote.GetActiveDevices()
            for x in range(0, 16):
                if addresses.IsSet(x):
                    vendorId = self.remote.GetDeviceVendorId(x)
                    cecVersion = self.remote.GetDeviceCecVersion(x)
                    power = self.remote.GetDevicePowerStatus(x)
                    self.log.debug(
                        f"device #{x}: {self.remote.LogicalAddressToString(x)}")
                    self.log.debug(
                        f"address: {self.remote.GetDevicePhysicalAddress(x)}")
                    self.log.debug(
                        f"active source: {self.remote.IsActiveSource(x)}")
                    self.log.debug(
                        f"vendor: {self.remote.VendorIdToString(vendorId)}")
                    self.log.debug(
                        f"CEC version: {self.remote.CecVersionToString(cecVersion)}")
                    self.log.debug(
                        f"OSD name: {self.remote.GetDeviceOSDName(x)}")
                    self.log.debug(
                        f"power status: {self.remote.PowerStatusToString(power)}")
            self.display_id = 0  # 0 = 'TV'

    @intent_handler("CaptureSingleShot.intent")
    def handle_capture_single_shot(self, _):
        """Take a picture."""
        self.speak_dialog("acknowledge")
        self.gui["singleshot_mode"] = False
        self.take_single_photo()

    @intent_handler("OpenCamera.intent")
    def handle_open_camera(self, _):
        """Open the Camera GUI providing a live view of the camera.

        Provides a button to take the photo.
        Back button to immediately return to Homescreen.
        """
        self.speak_dialog("acknowledge")
        self.gui["singleshot_mode"] = False
        self.handle_camera_activity("generic")

    @intent_handler(
        IntentBuilder("CompleteCam")
        .require("shutdown")
        .require("cam")
    )
    def handle_camera_completed(self, _=None):
        """Close the Camera GUI when finished."""
        self.gui.remove_page("Camera.qml")
        self.gui.release()
        self.log.debug(f"{self.display_status}")
        if self.display_status == "standby":
            x = self.remote.StandbyDevices(self.display_id)
            self.log.debug(f"Switched to standby: {x}")

    def handle_camera_status(self, message):
        """Handle Camera GUI status changes."""
        current_status = message.data.get("status")
        if current_status == "generic":
            self.gui["singleshot_mode"] = False
        if current_status == "imagetaken":
            self.gui["singleshot_mode"] = False
        if current_status == "singleshot":
            self.gui["singleshot_mode"] = True

    @skill_api_method
    def take_single_photo(self):
        """Take a single photo using the attached camera."""
        self.handle_camera_activity("singleshot")

    @skill_api_method
    def open_camera_app(self):
        """Open the camera live view mode."""
        self.handle_camera_activity("generic")

    def handle_camera_activity(self, activity):
        """Perform camera action.

        Arguments:
            activity (str): the type of action to take, one of:
                "generic" - open the camera app
                "singleshot" - take a single photo
        """
        self.gui["save_path"] = self.save_folder
        if activity == "singleshot":
            self.gui["singleshot_mode"] = True
        if activity == "generic":
            self.gui["singleshot_mode"] = False
        self.gui.show_page("Camera.qml", override_idle=True,
                           override_animations=True)

    @intent_handler(
        IntentBuilder("StreamCam")
        .one_of("view", "view.short")
        .optionally("location")
    )
    def handle_get_stream(self, message):
        if self.display:
            cam_name = message.data.get("location")
            self.log.debug(f"Cam Name: {cam_name}")
            idle = 60 if message.data.get("view.short", False) \
                else True
            self.log.debug(f"Idle: {idle}")
            if not cam_name:
                self.speak_dialog("stream.not_specified")
                return

            cam_url = self.cams.get(cam_name, None)
            if not cam_url:
                self.speak_dialog("stream.no_config", data={"cam": cam_name})
                return
            else:
                self.show_stream(cam_url, idle)
        else:
            self.speak_dialog("display.not.available")

    # stream called based on a bus message (the message utterance value must equal to the cam url key)
    def handle_stream(self, message, idle=60):
        cam_name = message.data.get("utterance")
        cam_url = self.cams.get(cam_name, None)
        self.show_stream(cam_url, idle)

    def show_stream(self, cam_url, idle):
        # determine if we have to have to standby the disp afterwards
        _display_status_code = \
            self.remote.GetDevicePowerStatus(self.display_id)
        self.display_status = \
            self.remote.PowerStatusToString(_display_status_code)
        self.log.debug(f"Display Status: {self.display_status}")
        # make it the active source, this is causing
        # 1) turn on display on input source (HDMI/..) or
        # 2) switch to HDMI/... if the diaplay is already on
        if self.remote.SetActiveSource(cec.CEC_DEVICE_TYPE_RESERVED):
            self.gui.show_url(cam_url, override_idle=idle)
        if idle is not True:
            sleep(idle-2)
            self.handle_camera_completed()

    def stop(self):
        """Respond to system stop command."""
        self.handle_camera_completed()


def create_skill():
    """Create Skill for registration in Mycroft."""
    return CameraSkill()

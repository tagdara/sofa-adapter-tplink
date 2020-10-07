#!/usr/bin/python3

import sys, os
# Add relative paths for the directory where the adapter is located as well as the parent
sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__),'../../base'))

from sofabase import sofabase, adapterbase, configbase
import devices
import datetime

import math
import random
from collections import namedtuple

import json
import asyncio
import copy

#import pyHS100
import kasa

class tplink(sofabase):
    
    class adapter_config(configbase):
    
        def adapter_fields(self):
            self.power_strips=self.set_or_default('power_strips', default=[])
            self.plugs=self.set_or_default('plugs', default=[])
            self.type_other=self.set_or_default('type_other', default=[])
    
    class EndpointHealth(devices.EndpointHealth):

        @property            
        def connectivity(self):
            return 'OK'

    class EnergySensor(devices.EnergySensor):

        @property            
        def voltage(self):
            try:
                return int(self.nativeObject['energy']['voltage_mv']/1000)
            except:
                self.log.error('.. error getting voltage', exc_info=True)
            return 0

        @property            
        def current(self):
            try:
                return self.nativeObject['energy']['current_ma']/1000
            except:
                self.log.error('.. error getting current', exc_info=True)
            return 0
            
        @property            
        def power(self):
            try:
                return int(self.nativeObject['energy']['power_mw']/1000)
            except:
                self.log.error('.. error getting power', exc_info=True)
            return 0

        @property            
        def total(self):
            try:
                return int(self.nativeObject['energy']['total_wh'])
            except:
                self.log.error('.. error getting total watt hours', exc_info=True)
            return 0

    class EnergyModeController(devices.ModeController):

        @property            
        def mode(self):
            try:
                if not self.nativeObject['is_on']: return "Off"
                watts=int(self.nativeObject['energy']['power_mw']/1000)
                if watts<3: return "Standby"
                if watts<10: return "Low"
                if watts<51: return "Medium"
                return "High"
            except:
                self.adapter.log.error('Error computing energy mode level: %s' % self.nativeObject, exc_info=True)
            return "Off"


    class PowerController(devices.PowerController):

        @property            
        def powerState(self):
            try:
                return "ON" if self.nativeObject['is_on'] else "OFF"
            except:
                self.adapter.log.error('!! Error getting powerstate', exc_info=True)
                return "OFF"


        async def TurnOn(self, correlationToken='', **kwargs):
            try:
                plug=self.adapter.plugs[self.nativeObject['id']]
                await plug.turn_on()
                await self.adapter.getManual(update=False)
                return self.device.Response(correlationToken)       
            except:
                self.adapter.log.error('!! Error during TurnOn', exc_info=True)
                return {}
 
        
        async def TurnOff(self, correlationToken='', **kwargs):

            try:
                plug=self.adapter.plugs[self.nativeObject['id']]
                await plug.turn_off()
                await self.adapter.getManual(update=False)
                return self.device.Response(correlationToken)       
            except:
                self.adapter.log.error('!! Error during TurnOff', exc_info=True)
                return {}
    
    
    class adapterProcess(adapterbase):
    
        def __init__(self, log=None, loop=None, dataset=None, notify=None, request=None, executor=None, config=None, **kwargs):
            self.config=config
            self.dataset=dataset
            self.dataset.nativeDevices['plug']={}
            self.dataset.nativeDevices['strip']={}
            self.log=log
            self.notify=notify
            self.polltime=5
            self.loop=loop
            self.inuse=False
            self.strips={}
            self.plugs={}

 
        async def pre_activate(self):
            self.log.info('.. Starting TPlink')
            await self.initialize_devices()
            await self.getManual()
            
        async def start(self):
            self.polling_task = asyncio.create_task(self.pollTPLink())


        async def initialize_devices(self):
            try:
                for dev in self.config.power_strips:
                    self.log.info('.. collecting data for %s' % dev)
                    strip = kasa.SmartStrip(dev)
                    await strip.update()
                    strip_id=strip.device_id.replace(":","")
                    #self.log.info('strip %s: %s' % (dev, strip.hw_info))
                    self.strips[strip_id]=strip
                            
                    for dev in self.config.plugs:
                        plug = kasa.SmartPlug(dev)
                        await plug.update()
                        plug_id=plug.device_id.replace(":","")
                        #self.log.info('plug %s: %s' % (dev, plug.hw_info))
                        self.plugs[plug_id]=plug
            except:
                self.log.error('Error initializing devices', exc_info=True)


        async def get_plug(self, plug, parent=None, update=True):
            try:
                self.log.debug('.. updating %s' % plug.device_id)
                if update and "_" not in plug.device_id:
                    await plug.update()
                if "_" in plug.device_id:
                    short_id=plug.device_id.split("_")[1]
                else:
                    short_id=plug.device_id
                plug_data={"hw_info": plug.hw_info, "parent_id": parent, "id": short_id, "alias": plug.alias, "led": plug.led, "is_on": plug.is_on==1, "model":plug.model}

                if plug.is_on:
                    plug_data["on_since"]=plug.on_since.isoformat()
                plug_data["energy"]=await plug.get_emeter_realtime()
                
                return plug_data
            except kasa.smartdevice.SmartDeviceException:
                self.log.error('!! error getting plug (communication error)')
            except:
                self.log.error('.. error getting plug', exc_info=True)


        async def get_strip(self, strip, update=True):
            try:
                self.log.debug('.. updating %s' % strip.device_id)
                if update:
                    await strip.update()
                strip_data={"hw_info": strip.hw_info, "mac": strip.device_id, "id": strip.device_id.replace(":",""), "alias": strip.alias, "led": strip.led, "is_on": strip.is_on==1, "model":strip.model}
                
                plug_data={}
                for plug in strip.plugs:
                    plug_info=await self.get_plug(plug, parent=strip.device_id, update=False)
                    plug_data[plug.device_id]=plug_info
                    self.plugs[plug.device_id.split('_')[1]]=plug  
                    
                return {'strip': strip_data, 'plugs': plug_data }
            except kasa.smartdevice.SmartDeviceException:
                self.log.error('!! error getting strip (communication error)')
            except:
                self.log.error('!! error getting strip', exc_info=True)
            

        async def getManual(self, device_id=None, update=True):
            try:
                #timestart=datetime.datetime.now()
                for strip_id in self.strips:
                    strip_data=await self.get_strip(self.strips[strip_id], update=update)
                    if strip_data:
                        #self.log.info("~~~~1 %s" % {'strip': { strip_id: strip_data['strip']}})
                        await self.dataset.ingest({'strip': { strip_id: strip_data['strip']}}, mergeReplace=True)
                        for plug_id in strip_data['plugs']:
                            short_id=plug_id.split("_")[1]
                            #self.log.info("~~~~1 %s" % {'plug': { short_id: strip_data['plugs'][plug_id] }} )
                            await self.dataset.ingest({'plug': { short_id: strip_data['plugs'][plug_id] }}, mergeReplace=True)
                    else:
                        self.log.warning('!. strip update returned no data for %s' % strip_id)

                for plug_id in self.plugs:
                    if '_' not in self.plugs[plug_id].device_id or device_id==plug_id:
                        plug_data=await self.get_plug(self.plugs[plug_id], update=update)
                        if plug_data:
                            await self.dataset.ingest({'plug': { plug_id: plug_data }}, mergeReplace=True)
                        else:
                            self.log.warning('!. plug update returned no data for %s' % plug_id)
                        
                #td=datetime.datetime.now()-timestart
                #self.log.debug('.. got data in %s' % td)
            except kasa.smartdevice.SmartDeviceException:
                self.log.warn('Error discovering devices - socket timeout / temporary commmunication error')
            except:
                self.log.error('Error polling devices', exc_info=True)

            
        async def pollTPLink(self):
            active=True
            while active:
                try:
                    #self.log.info("Polling bridge data")
                    await self.getManual()
                    await asyncio.sleep(self.polltime)
                except:
                    self.log.error('Error fetching TP link Bridge Data', exc_info=True)
                    active=False

        # Adapter Overlays that will be called from dataset
        async def addSmartDevice(self, path):
            try:
                device_id=path.split("/")[2]
                device_type=path.split("/")[1]
                endpointId="%s:%s:%s" % ("hue", device_type, device_id)
                if endpointId not in self.dataset.localDevices:  # localDevices/friendlyNam   
                    if device_type=="plug":
                        #self.log.info('device path: %s' % path)
                        nativeObject=self.dataset.nativeDevices['plug'][device_id]
                        return await self.addSmartPlug(device_id, nativeObject)
            except:
                self.log.error('Error defining smart device', exc_info=True)
            return False


        async def addSmartPlug(self, deviceid, nativeObject):
            
            try:
                if deviceid in self.config.type_other:
                    displayCategories=['OTHER']
                else:
                    displayCategories=['SMARTPLUG']
                device=devices.alexaDevice('tplink/plug/%s' % deviceid, nativeObject['alias']+" outlet", displayCategories=displayCategories, adapter=self)
                device.PowerController=tplink.PowerController(device=device)
                device.EndpointHealth=tplink.EndpointHealth(device=device)
                # TODO/CHEESE - 10/3/20 Waiting to see what happens with Alexa.DeviceUsage.Meter API once released
                #device.EnergySensor=tplink.EnergySensor(device=device)
                # In the meantime, switching to a mode controller which should generate far fewer changereports
                device.EnergyModeController=tplink.EnergyModeController('Energy Level', device=device, 
                    supportedModes={'Off':'Off', 'Low':'Low', 'Medium': 'Medium', 'High':'High'})

                return self.dataset.add_device(device)
            except:
                self.log.error('Error adding smart plug', exc_info=True)
            return False


if __name__ == '__main__':
    adapter=tplink(name='tplink')
    adapter.start()

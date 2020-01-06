#!/usr/bin/python3

import sys, os
# Add relative paths for the directory where the adapter is located as well as the parent
sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__),'../../base'))

from sofabase import sofabase
from sofabase import adapterbase
import devices

import math
import random
from collections import namedtuple

import json
import asyncio
import copy

import pyHS100

class tplink(sofabase):
    
    class EndpointHealth(devices.EndpointHealth):

        @property            
        def connectivity(self):
            return 'OK'

    class PowerController(devices.PowerController):

        @property            
        def powerState(self):
            try:
                if 'state' in self.nativeObject:
                    return "ON" if self.nativeObject['state'] else "OFF"
                elif 'relay_state' in self.nativeObject:
                    return "ON" if self.nativeObject['relay_state'] else "OFF"
            except:
                self.adapter.log.error('!! Error getting powerstate', exc_info=True)
                return "OFF"

        async def TurnOn(self, correlationToken='', **kwargs):
            try:
                if 'parent' in self.nativeObject:
                    plug=self.adapter.getParentStripObject(self.nativeObject['parent']).plugs[self.nativeObject['child_index']]
                else:
                    plug=plugpyHS100.SmartPlug(self.nativeObject['address'])

                plug.state='ON'
                await self.adapter.getManual()
                return self.device.Response(correlationToken)       
            except:
                self.adapter.log.error('!! Error during TurnOn', exc_info=True)
                return {}
        
        async def TurnOff(self, correlationToken='', **kwargs):

            try:
                if 'parent' in self.nativeObject:
                    plug=self.adapter.getParentStripObject(self.nativeObject['parent']).plugs[self.nativeObject['child_index']]
                else:
                    plug=plugpyHS100.SmartPlug(self.nativeObject['address'])

                plug.state='OFF'
                            
                await self.adapter.getManual()
                return self.device.Response(correlationToken)       
            except:
                self.adapter.log.error('!! Error during TurnOff', exc_info=True)
                return {}
    
    class adapterProcess(adapterbase):
    
        def __init__(self, log=None, loop=None, dataset=None, notify=None, request=None, **kwargs):
            self.dataset=dataset
            self.dataset.nativeDevices['plug']={}
            self.dataset.nativeDevices['strip']={}
            self.log=log
            self.notify=notify
            self.polltime=5
            self.loop=loop
            self.inuse=False
            
        async def start(self):
            self.log.info('.. Starting TPlink')
            await self.getManual()
            await self.discover()
            await self.pollTPLink()

        async def getManual(self):
            try:
                if 'strips' in self.dataset.config:
                    for dev in self.dataset.config['strips']:
                        strip = pyHS100.SmartStrip(dev)
                        sysinfo=strip.get_sysinfo()
                        sysinfo['address']=dev
                        await self.dataset.ingest({'strip': { sysinfo['deviceId']: sysinfo}}, mergeReplace=True)
                        for i,child_plug in enumerate(sysinfo['children']):
                            child_plug['parent']=sysinfo['deviceId']
                            child_plug['child_index']=i
                            await self.dataset.ingest({'plug': { child_plug['id']: child_plug }})
                        #self.log.info("ON: %s" % strip.state)
                
                if 'plugs' in self.dataset.config:
                    for dev in self.dataset.config['plugs']:
                        plug = pyHS100.SmartPlug(dev)
                        sysinfo=plug.get_sysinfo()
                        sysinfo['address']=dev
                        await self.dataset.ingest({'plug': { sysinfo['deviceId']: sysinfo}})
            except pyHS100.smartdevice.SmartDeviceException:
                self.log.warn('Error discovering devices - temporary commmunication error', exc_info=True)

            except:
                self.log.error('Error polling devices', exc_info=True)
                
            
        async def discover(self):
            try:
                self.log.info('Discovering TPlink devices')
                devs=pyHS100.Discover.discover().values()
                if devs:
                    for dev in pyHS100.Discover.discover().values():
                        self.log.info('Discovered device: %s' % dev)
                else:
                    self.log.warn('No devices discovered')
            except:
                self.log.error('Error discovering devices', exc_info=True)
            
        async def pollTPLink(self):
            while True:
                try:
                    #self.log.info("Polling bridge data")
                    await self.getManual()
                    await asyncio.sleep(self.polltime)
                except:
                    self.log.error('Error fetching Hue Bridge Data', exc_info=True)


        # Adapter Overlays that will be called from dataset
        async def addSmartDevice(self, path):
            
            #self.log.info('Path: %s' % path)
            try:
                if path.split("/")[1]=="plug":
                    #self.log.info('device path: %s' % path)
                    return await self.addSmartPlug(path.split("/")[2])
                    
                return False

            except:
                self.log.error('Error defining smart device', exc_info=True)
                return False


        async def addSmartPlug(self, deviceid):
            
            try:
                nativeObject=self.dataset.nativeDevices['plug'][deviceid]
                if nativeObject['alias'] not in self.dataset.localDevices:
                    if deviceid in self.dataset.config['other']:
                        displayCategories=['OTHER']
                    else:
                        displayCategories=['SWITCH']
                    device=devices.alexaDevice('tplink/plug/%s' % deviceid, nativeObject['alias'], displayCategories=displayCategories, adapter=self)
                    device.PowerController=tplink.PowerController(device=device)
                    device.EndpointHealth=tplink.EndpointHealth(device=device)
                    return self.dataset.newaddDevice(device)
                #self.log.info('%s %s' % (deviceid, self.dataset.localDevices))
                #nativeObject=self.dataset.nativeDevices['plug'][deviceid]
                #if nativeObject['alias'] not in self.dataset.localDevices:
                #    if deviceid in self.dataset.config['other']:
                #        displayCategories=['OTHER']
                #    else:
                #        displayCategories=['SWITCH']
                #    return self.dataset.addDevice(nativeObject['alias'], devices.switch('tplink/plug/%s' % deviceid, nativeObject['alias'], displayCategories=displayCategories, log=self.log))
    
                return False
            except:
                self.log.error('Error adding smart plug', exc_info=True)
                return False


        def updateSmartDevice(self, itempath, value):

            try:
                nativeObject=self.dataset.getObjectFromPath(self.dataset.getObjectPath(itempath))
                self.log.info('Checking object for controllers: %s' % nativeObject)
                
                try:
                    detail=itempath.split("/",3)[3]
                except:
                    detail=""

                controllerlist={}
                
                if detail=="state" or detail=="relay_state" or detail=="":
                    controllerlist["PowerController"]=["powerState"]

                return controllerlist
            except KeyError:
                pass
            except:
                self.log.error('Error getting virtual controller types for %s' % itempath, exc_info=True)
                
        def getNativeFromEndpointId(self, endpointId):
            
            try:
                return endpointId.split(":")[2]
            except:
                return False
                
        def getParentStripObject(self, parentId):
            
            try:
                if parentId in self.dataset.nativeDevices['strip']:
                    return pyHS100.SmartStrip(self.dataset.nativeDevices['strip'][parentId]['address'])
                return None
            except:
                self.log.error('Error getting parent', exc_info=True)
                return None
                
        async def processDirective(self, endpointId, controller, command, payload, correlationToken='', cookie={}):

            try:
                device=endpointId.split(":")[2]
                nativeCommand={}
                

                if controller=="PowerController":
                    if device in self.dataset.nativeDevices['plug']:
                        dev=self.dataset.nativeDevices['plug'][device]
                        if 'parent' in dev:
                            plug=self.getParentStripObject(dev['parent']).plugs[dev['child_index']]
                        else:
                            plug=plugpyHS100.SmartPlug(dev['address'])
                        
                        if command=='TurnOn':
                            plug.state='ON'
                        elif command=='TurnOff':
                            plug.state='OFF'
                            
                    await self.getManual()
                        
                    response=await self.dataset.generateResponse(endpointId, correlationToken)
                    return response
                    
            except:
                self.log.error('Error executing state change.', exc_info=True)


        def virtualControllers(self, itempath):

            try:
                nativeObject=self.dataset.getObjectFromPath(self.dataset.getObjectPath(itempath))
                self.log.debug('Checking object for controllers: %s' % nativeObject)
                
                try:
                    detail=itempath.split("/",3)[3]
                except:
                    detail=""

                controllerlist={}

                if detail=="state" or detail=="relay_state" or detail=="":
                    controllerlist["PowerController"]=["powerState"]

                return controllerlist
            except KeyError:
                pass
            except:
                self.log.error('Error getting virtual controller types for %s' % itempath, exc_info=True)

            
        def virtualControllerProperty(self, nativeObj, controllerProp):
            
            try:
                    
                if controllerProp=='powerState':
                    if 'state' in nativeObj:
                        return "ON" if nativeObj['state'] else "OFF"
                    elif 'relay_state' in  nativeObj:
                        return "ON" if nativeObj['relay_state'] else "OFF"

            except:
                self.log.error('Error converting virtual controller property: %s %s' % (controllerProp, nativeObj), exc_info=True)
                
                


if __name__ == '__main__':
    adapter=tplink(name='tplink')
    adapter.start()

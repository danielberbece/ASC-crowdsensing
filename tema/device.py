"""
This module represents a device.

Computer Systems Architecture Course
Assignment 1
March 2019
"""

from threading import Event, Thread, BoundedSemaphore
from Queue import Queue
from barrier import ReusableBarrier

class Device(object):
    """
    Class that represents a device.
    """

    def __init__(self, device_id, sensor_data, supervisor):
        """
        Constructor.

        @type device_id: Integer
        @param device_id: the unique id of this node; between 0 and N-1

        @type sensor_data: List of (Integer, Float)
        @param sensor_data: a list containing (location, data) as measured by this device

        @type supervisor: Supervisor
        @param supervisor: the testing infrastructure's control and validation component
        """
        self.device_id = device_id
        self.sensor_data = sensor_data
        self.supervisor = supervisor
        self.script_received = Event()
        self.scripts = []
        self.location_locks = []
        self.timepoint_done = Event()
        self.barrier = None
        self.thread = DeviceThread(self)
        self.thread.start()
        self.scriptsLock = BoundedSemaphore(1)

    def __str__(self):
        """
        Pretty prints this device.

        @rtype: String
        @return: a string containing the id of this device
        """
        return "Device %d" % self.device_id

    def setup_devices(self, devices):
        """
        Setup the devices before simulation begins.

        @type devices: List of Device
        @param devices: list containing all devices
        """
        if self.device_id == 0:
            # Make script running atomic using BoundedSemaphore
            for _ in range(100):
                self.location_locks.append(BoundedSemaphore(1))

            # Initialize reusable barrier
            self.barrier = ReusableBarrier(len(devices))

            # Use the same variables for all devices
            for dev in devices:
                if dev != self:
                    dev.location_locks = self.location_locks
                    dev.barrier = self.barrier

    def assign_script(self, script, location):
        """
        Provide a script for the device to execute.

        @type script: Script
        @param script: the script to execute from now on at each timepoint; None if the
            current timepoint has ended

        @type location: Integer
        @param location: the location for which the script is interested in
        """
        if script is not None:
            self.scriptsLock.acquire()
            self.scripts.append((script, location))
            self.scriptsLock.release()
            self.script_received.set()
        else:
            self.timepoint_done.set()

    def get_data(self, location):
        """
        Returns the pollution value this device has for the given location.

        @type location: Integer
        @param location: a location for which obtain the data

        @rtype: Float
        @return: the pollution value
        """
        if location in self.sensor_data:
            return self.sensor_data[location]
        else:
            return None

    def set_data(self, location, data):
        """
        Sets the pollution value stored by this device for the given location.

        @type location: Integer
        @param location: a location for which to set the data

        @type data: Float
        @param data: the pollution value
        """
        if location in self.sensor_data:
            self.sensor_data[location] = data

    def shutdown(self):
        """
        Instructs the device to shutdown (terminate all threads). This method
        is invoked by the tester. This method must block until all the threads
        started by this device terminate.
        """
        self.thread.join()

class DeviceThread(Thread):
    """
    Class that implements the device's worker thread.
    """

    def __init__(self, device):
        """
        Constructor.

        @type device: Device
        @param device: the device which owns this thread
        """
        Thread.__init__(self, name="Device Thread %d" % device.device_id)
        self.device = device
        self.thread_pool = ThreadPool(device, 8)


    def run(self):
        self.thread_pool.start_workers()

        # hope there is only one timepoint, as multiple iterations of the loop are not supported
        while True:
            # get the current neighbourhood
            neighbours = self.device.supervisor.get_neighbours()
            if neighbours is None:
                break

            while (True):
                if self.device.script_received.isSet():
                    self.device.scriptsLock.acquire()
                    for (script, location) in self.device.scripts:
                        self.thread_pool.add_script(script, neighbours, location)
                    self.device.script_received.clear()
                    self.device.scripts = []
                    self.device.scriptsLock.release()
                if self.device.timepoint_done.isSet():
                    self.device.timepoint_done.clear()
                    self.device.script_received.set()
                    break
            
            self.thread_pool.wait()
            self.device.barrier.wait()

        self.thread_pool.terminate()
      
class Worker(Thread):
    """ Thread executing tasks from a given tasks queue """
    def __init__(self, queue, device):
        Thread.__init__(self)
        self.queue = queue
        self.device = device

    def run(self):
        while True:
            script, neighbours, location = self.queue.get()

            if script is None and location is None and neighbours is None:
                self.queue.task_done()
                return

            script_data = []
            self.device.location_locks[location].acquire()
            # collect data from current neighbours
            for device in neighbours:
                data = device.get_data(location)
                if data is not None:
                    script_data.append(data)
            # add our data, if any
            data = self.device.get_data(location)
            if data is not None:
                script_data.append(data)

            if script_data != []:
                # run script on data
                result = script.run(script_data)

                # update data of neighbours, hope no one is updating at the same time
                for device in neighbours:
                    device.set_data(location, result)
                # update our data, hope no one is updating at the same time
                self.device.set_data(location, result)
                self.device.location_locks[location].release()
            self.queue.task_done()


class ThreadPool:
    """ Pool of threads consuming tasks from a queue """
    def __init__(self, device, num_threads):
        self.queue = Queue(num_threads)
        self.workers = []
        for _ in range(num_threads):
            self.workers.append(Worker(self.queue, device))
        self.device = device

    def start_workers(self):
        for th in self.workers:
            th.start()

    def add_script(self, script, neighbours, location):
        """ Add a task to the queue """
        self.queue.put((script, neighbours, location))

    def wait(self):
        self.queue.join()

    def terminate(self):
        """ Wait for completion of all the workers in the queue """
        self.queue.join()
        for _ in range(len(self.workers)):
            self.add_script(None, None, None)

        for worker in self.workers:
            worker.join()

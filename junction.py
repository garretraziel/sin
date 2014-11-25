#!/usr/bin/env python

import sys
import simpy
import simpy.rt
import random

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d

verbose = False
pretty_print = False

counter = 0
counter_last = 0
served = 0
served_last = 0
waited_average = 0
queue_wa = {"we": (0, 0), "ew": (0, 0), "ns": (0, 0), "sn": (0, 0)}

monitor_data = []

start_hour = 0
day_coef = [0.05,0.01,0.01,0.01,0.1,0.5,1.0,2.0,3.0,3.5,2.0,1.0,1.0,1.5,2.0,3.0,3.5,3.0,2.0,1.0,0.75,0.5,0.25,0.1]
cars = []

waited_average_actual_interval = 0
s_actual_interval = 0
waited_average_actual = []

class Car(object):
    def __init__(self, env, junction, traffic_light, i, direction):
        self.env = env
        self.junction = junction
        self.traffic_light = traffic_light
        self.i = i
        self.direction = direction
        self.going_through_time = random.uniform(3, 10)
        self.action = env.process(self.go())

    def go(self):
        global served, verbose, waited_average, queue_wa, waited_average_actual_interval, s_actual_interval
        if verbose:
            print '%d: %d arrived, will go %s' % (self.env.now, self.i, self.direction)

        started = self.env.now

        # fronta na prvni misto u semaforu
        # de fakto jenom tupe stoji ve fronte a teprve az se dostane do junction,
        # tak se diva, jestli muze jet nebo ne
        with self.junction.request() as req:
            yield req  # cekani na prvni misto
            
            #uvolnilo se misto pred autem, auto se posunuje, trva chvili nez se rozjede
            yield self.env.timeout(random.uniform(1,3))  # X sekund trva rozjizdeni aut

            while True:
                if verbose:
                    print '%d: %d is waiting for green' % (self.env.now, self.i)

                if self.traffic_light.state == "green":
                    #jestli je zelena, tak pokracuje bez cekani (nerozjizdi se, jede dal)
                    break
                else:
                    #ceka na semaforu
                    yield self.env.process(self.traffic_light.wait()) 
                    #chvili trva nez se rozjede
                    yield self.env.timeout(random.uniform(1,3))


                """
                #cekani na zelenou na semaforu
                yield self.env.process(self.traffic_light.wait()) 
                if verbose:
                    print '%d: %d is free to go %s' % (self.env.now, self.i, self.direction)
                yield self.env.timeout(random.uniform(1,3))  # X sekund trva rozjizdeni aut

                break
                if self.traffic_light.state == "green":
                    break
                """


            waited = self.env.now - started
            waited_average += waited
            waited_average_actual_interval += waited
            q_avg = queue_wa[self.direction]
            queue_wa[self.direction] = (q_avg[0] + waited, q_avg[1] + 1)

            #yield self.env.timeout(self.going_through_time)  # doba prujezdu krizovatkou
            if verbose:
                print '%d: %d passed junction going %s' % (self.env.now, self.i, self.direction)
            served += 1
            s_actual_interval += 1


class TrafficLight(object):
    def __init__(self, env, direction, init_state, starting):
        self.env = env
        self.direction = direction
        self.state = init_state
        self.starting = starting
        self.switch_event = env.event()

    def wait(self):
        # pokud je na semaforu cervena, cekat na event prepnuti na zelenou
        if self.state == "red":
            yield self.switch_event  # cekani na zelenou, spoustena TimedControlLogic
            yield self.env.timeout(self.starting)  # X sekund trva rozjizdeni aut
        # skonci proces wait, auto muze jet


class TimedControlLogic(object):
    def __init__(self, env, light_time, offset_time, tl_we, tl_ew, tl_ns, tl_sn):
        self.env = env
        self.traffic_lights = {"we": tl_we, "ew": tl_ew, "ns": tl_ns, "sn": tl_sn}
        self.action = env.process(self.run())
        self.light_time = light_time
        self.offset_time = offset_time

    def run(self):
        global verbose
        order = [("we", "ew"), ("ns", "sn")]
        o_cnt = 0
        while True:
            old = o_cnt
            o_cnt = (o_cnt + 1) % len(order)

            yield self.env.timeout(self.light_time)  # cekani s rozsvicenymi svetly

            # zastaveni jednoho smeru
            self.traffic_lights[order[old][0]].state = "red"
            self.traffic_lights[order[old][1]].state = "red"

            yield self.env.timeout(self.offset_time)  # offset pro dojezd aut

            if verbose:
                print '%d: %s are good to go' % (self.env.now, " and ".join(order[o_cnt]))
            # pusteni druheho smeru
            self.traffic_lights[order[o_cnt][0]].state = "green"
            self.traffic_lights[order[o_cnt][1]].state = "green"
            # spusti se udalosti tech, co cekali na cervenou
            self.traffic_lights[order[o_cnt][0]].switch_event.succeed()
            self.traffic_lights[order[o_cnt][0]].switch_event = self.env.event()
            self.traffic_lights[order[o_cnt][1]].switch_event.succeed()
            self.traffic_lights[order[o_cnt][1]].switch_event = self.env.event()


def car_generator(env, interval, junction, traffic_light, direction):
    global counter
    while True:

        hour = (int(round(env.now / 3600.0)) + start_hour) % 24

        interval_x = interval / day_coef[hour]

        # vygeneruju auto
        Car(env, junction, traffic_light, counter, direction)
        counter += 1
        # uspim se na nejakou dobu
        yield env.timeout(random.expovariate(1.0 / interval_x))


def monitor(env, interval, j_we, j_ew, j_ns, j_sn):
    global served, counter, waited_average, queue_wa, counter_last, served_last, monitor_data, cars, waited_average_actual_interval, waited_average_actual, s_actual_interval
    while True:
        s = served - served_last
        c = counter - counter_last
        
        served_last = served
        counter_last = counter
        if pretty_print:
            print "-"*20
            print "On %d:" % env.now
            print "Served: %d cars from %d (%.1f %%)" % (s, c, (s / float(c) * 100))
            print "Average waiting time: %.1f" % ((waited_average / float(served)) if served != 0 else 0)
            print "Queue count: %d %d %d %d" % (len(j_we.queue), len(j_ew.queue), len(j_ns.queue), len(j_sn.queue))
            print "Average waiting time for queues: %.1f %.1f %.1f %.1f" % (
                queue_wa["we"][0]/float(queue_wa["we"][1]) if queue_wa["we"][1] else 0,
                queue_wa["ew"][0]/float(queue_wa["ew"][1]) if queue_wa["ew"][1] else 0,
                queue_wa["ns"][0]/float(queue_wa["ns"][1]) if queue_wa["ns"][1] else 0,
                queue_wa["sn"][0]/float(queue_wa["sn"][1]) if queue_wa["sn"][1] else 0
            )
        else:
            print "%d %.1f %.1f %d %d %d %d" % (
                env.now, ((s / float(c) * 100) if c != 0 else 0), (waited_average / float(served)) if served != 0 else 0,
                len(j_we.queue), len(j_ew.queue), len(j_ns.queue), len(j_sn.queue)
            )

        monitor_data.append((
                env.now, ((s / float(c) * 100) if c != 0 else 0), (waited_average / float(served)) if served != 0 else 0,
                len(j_we.queue), len(j_ew.queue), len(j_ns.queue), len(j_sn.queue)
            ))
        cars.append(c)

        if env.now % 600 == 0:
            waited_average_actual.append((waited_average_actual_interval/s_actual_interval) if s_actual_interval != 0 else 0)
            waited_average_actual_interval = 0
            s_actual_interval = 0

        yield env.timeout(interval)


def plot_data(running_time):
    data = np.array(monitor_data) / 60.0
    time = np.array(range(0, running_time, 60)) / 60

    plt.figure(1)

    plt.subplot(311)
    plt.plot(time, data[:,2])
    plt.ylabel('average waiting time cumulative')

    plt.subplot(312)
    plt.plot(np.array(range(0,running_time, 600))/60, np.array(waited_average_actual)/60.0)
    plt.ylabel('average waiting time')

    plt.subplot(313)
    plt.plot(time, cars)
    plt.ylabel('cars arrived')    
    plt.show()



def main(running_time):
    global served, counter, waited_average
    env = simpy.Environment()
    # env = simpy.rt.RealtimeEnvironment(factor=2.0)

    # semafory z jednotlivych smeru
    tl_we = TrafficLight(env, "we", "green", 4)
    tl_ew = TrafficLight(env, "ew", "green", 4)
    tl_ns = TrafficLight(env, "ns", "red", 4)
    tl_sn = TrafficLight(env, "sn", "red", 4)
    # rizeni prepinani semaforu
    TimedControlLogic(env, int(sys.argv[2]), 5, tl_we, tl_ew, tl_ns, tl_sn)

    # fronta na prvni misto
    j_we = simpy.Resource(env, capacity=1)
    j_ew = simpy.Resource(env, capacity=1)
    j_ns = simpy.Resource(env, capacity=1)
    j_sn = simpy.Resource(env, capacity=1)

    # generovani prijezdu aut
    podivny_parametr = 20

    env.process(car_generator(env, podivny_parametr, j_we, tl_we, "we"))
    env.process(car_generator(env, podivny_parametr, j_ew, tl_ew, "ew"))
    env.process(car_generator(env, podivny_parametr, j_ns, tl_ns, "ns"))
    env.process(car_generator(env, podivny_parametr, j_sn, tl_sn, "sn"))

    # sbirani statistik o simulaci
    env.process(monitor(env, 60, j_we, j_ew, j_ns, j_sn))

    env.run(until=running_time)

    plot_data(running_time)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print "%s running_time in hours" % sys.argv[0]
    else:
        main(int(sys.argv[1])*3600)
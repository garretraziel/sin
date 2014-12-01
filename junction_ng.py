#!/usr/bin/env python

import sys
import simpy
import simpy.rt
import random

import numpy as np
import matplotlib.pyplot as plt

counter = 0
counter_last = 0
queue_wa = {"we": (0, 0), "ew": (0, 0), "ns": (0, 0), "sn": (0, 0)}

start_hour = 0
day_coef = [0.05,0.01,0.01,0.05,0.1,0.5,1.0,2.0,3.0,3.5,2.5,2.2,2.0,2.2,2.5,3.0,3.5,3.0,2.0,1.0,0.75,0.5,0.25,0.1]
cars = []

wa_interval_ns = 0
s_ns = 0
wa_avg_ns = []

wa_interval_we = 0
s_we = 0
wa_avg_we = []

def monitor(env, interval, j_we, j_ew, j_ns, j_sn):
    global counter, counter_last, cars
    global wa_interval_ns, wa_avg_ns, s_ns, wa_interval_we, wa_avg_we, s_we
    while True:
        c = counter - counter_last
        
        counter_last = counter

        cars.append(c)

        if env.now % 600 == 0:
            wa_avg_ns.append((wa_interval_ns/s_ns) if s_ns != 0 else 0)
            wa_interval_ns = 0
            s_ns = 0
            wa_avg_we.append((wa_interval_we/s_we) if s_we != 0 else 0)
            wa_interval_we = 0
            s_we = 0

        yield env.timeout(interval)


def plot_data(running_time):
    time = np.array(range(0, running_time, 60)) / 60

    plt.figure(1)

    time10 = np.array(range(0,running_time, 600))/60

    plt.subplot(211)
    plt.plot(time10, np.array(wa_avg_ns)/60.0, "b-", time10, np.array(wa_avg_we)/60.0, "r-")
    plt.ylabel('average waiting time')
    plt.grid()

    plt.subplot(212)
    plt.plot(time, cars)
    plt.ylabel('cars arrived')    
    plt.grid()

    plt.show()


class Car(object):
    def __init__(self, env, junction, traffic_light, i, direction):
        self.env = env
        self.junction = junction
        self.traffic_light = traffic_light
        self.i = i
        self.direction = direction
        self.action = env.process(self.go())

    def go(self):
        global queue_wa, wa_interval_ns, s_ns, wa_interval_we, s_we
        started = self.env.now

        # fronta na prvni misto u semaforu
        # de fakto jenom tupe stoji ve fronte a teprve az se dostane do junction,
        # tak se diva, jestli muze jet nebo ne
        with self.junction.request() as req:
            yield req  # cekani na prvni misto
            
            #uvolnilo se misto pred autem, auto se posunuje, trva chvili nez se rozjede
            yield self.env.timeout(random.uniform(1.1, 2))  # X sekund trva rozjizdeni aut
            #yield self.env.timeout(4)  # X sekund trva rozjizdeni aut

            while True:
                if self.traffic_light.state == "green":
                    #jestli je zelena, tak pokracuje bez cekani (nerozjizdi se, jede dal)
                    break
                else:
                    #ceka na semaforu
                    yield self.env.process(self.traffic_light.wait()) 
                    #chvili trva nez se rozjede
                    yield self.env.timeout(random.uniform(1.1, 2))

            waited = self.env.now - started
            if self.direction == "ns" or self.direction == "sn":
                wa_interval_ns += waited
                s_ns += 1
            else:
                wa_interval_we += waited
                s_we += 1

            q_avg = queue_wa[self.direction]
            queue_wa[self.direction] = (q_avg[0] + waited, q_avg[1] + 1)


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


class TrafficLight(object):
    def __init__(self, env, direction, init_state):
        self.env = env
        self.direction = direction
        self.state = init_state
        self.switch_event = env.event()

    def wait(self):
        # pokud je na semaforu cervena, cekat na event prepnuti na zelenou
        if self.state == "red":
            yield self.switch_event  # cekani na zelenou, spoustena TimedControlLogic
        # skonci proces wait, auto muze jet


class TimedControlLogic(object):
    def __init__(self, env, light_time, offset_time, tls, _js):
        self.env = env
        self.traffic_lights = tls
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

            # pusteni druheho smeru
            self.traffic_lights[order[o_cnt][0]].state = "green"
            self.traffic_lights[order[o_cnt][1]].state = "green"
            # spusti se udalosti tech, co cekali na cervenou
            self.traffic_lights[order[o_cnt][0]].switch_event.succeed()
            self.traffic_lights[order[o_cnt][0]].switch_event = self.env.event()
            self.traffic_lights[order[o_cnt][1]].switch_event.succeed()
            self.traffic_lights[order[o_cnt][1]].switch_event = self.env.event()

class FuzzyControlLogic1(object):
    def __init__(self, env, _light_time, offset_time, tls, js):
        self.env = env
        self.traffic_lights = tls
        self.junctions = js
        self.action = env.process(self.run())
        self.offset_time = offset_time

    def run(self):
        global verbose
        order = [("we", "ew"), ("ns", "sn")]
        o_cnt = 0
        old = 1
        while True:

            aktualni = len(self.junctions[order[o_cnt][0]].queue) + len(self.junctions[order[o_cnt][1]].queue) +\
                self.junctions[order[o_cnt][0]].count + self.junctions[order[o_cnt][1]].count
            vedlejsi = len(self.junctions[order[old][0]].queue) + len(self.junctions[order[old][1]].queue) +\
                self.junctions[order[old][0]].count + self.junctions[order[old][1]].count

            interval___ = 30 if dlouhy_interval(aktualni, vedlejsi) else 5
            print aktualni, vedlejsi, interval___

            if decide(aktualni, vedlejsi):
                old = o_cnt
                o_cnt = (o_cnt + 1) % len(order)

                # zastaveni jednoho smeru
                self.traffic_lights[order[old][0]].state = "red"
                self.traffic_lights[order[old][1]].state = "red"

                yield self.env.timeout(self.offset_time)  # offset pro dojezd aut

                # pusteni druheho smeru
                self.traffic_lights[order[o_cnt][0]].state = "green"
                self.traffic_lights[order[o_cnt][1]].state = "green"
                # spusti se udalosti tech, co cekali na cervenou
                self.traffic_lights[order[o_cnt][0]].switch_event.succeed()
                self.traffic_lights[order[o_cnt][0]].switch_event = self.env.event()
                self.traffic_lights[order[o_cnt][1]].switch_event.succeed()
                self.traffic_lights[order[o_cnt][1]].switch_event = self.env.event()

            yield self.env.timeout(5)

class FuzzyControlLogic2(object):
    def __init__(self, env, _light_time, offset_time, tls, js):
        self.env = env
        self.traffic_lights = tls
        self.junctions = js
        self.action = env.process(self.run())
        self.offset_time = offset_time
        
        #maximum time for green light
        self.max_green_time = 60

        #loop time - how often question switching
        self.loop_time = 1
        #constants for traffic
        self.low_traf_max = 18
        self.med_traf_min = 0
        self.med_traf_max = 36
        self.hig_traf_min = 18
        self.hig_traf_max = 36
        #time constants
        self.low_time_max = 27
        self.med_time_min = 0
        self.med_time_max = 54
        self.hig_time_min = 27
        self.hig_time_max = 54

    #traffic functions
    def traffic_low(self, traffic):
        return max(((-traffic) / self.low_traf_max) + 1, 0)
    
    def traffic_med(self, traffic):
        if(traffic < ((self.med_traf_min + self.med_traf_max) / 2)):
            return max(0, ( traffic - self.med_traf_min) / ((self.med_traf_max - self.med_traf_min) / 2))
        else:
            return max(0, (-traffic + self.med_traf_max) / ((self.med_traf_max - self.med_traf_min) / 2))
    
    def traffic_hig(self, traffic):
        if(traffic < self.hig_traf_max):
            return max(0, ( traffic - self.hig_traf_min) / (self.hig_traf_max - self.hig_traf_min))
        else:
            return 1
     
     #light functions
    def time_low(self, time):
        return max(((-time) / self.low_time_max) + 1, 0)
    
    def time_med(self, time):
        if(time < ((self.med_time_min + self.med_time_max) / 2)):
            return max(0, ( time - self.med_time_min) / ((self.med_time_max - self.med_time_min) / 2))
        else:
            return max(0, (-time + self.med_time_max) / ((self.med_time_max - self.med_time_min) / 2))
    
    def time_hig(self, time):
        if(time < self.hig_time_max):
            return max(0, ( time - self.hig_time_min) / (self.hig_time_max - self.hig_time_min))
        else:
            return 1

    def fuzzySwitch(self, time, current_traf, opposing_traf):
        lll = min(self.traffic_low(current_traf), self.traffic_low(opposing_traf), self.time_low(time)) #
        mll = min(self.traffic_med(current_traf), self.traffic_low(opposing_traf), self.time_low(time))
        hll = min(self.traffic_hig(current_traf), self.traffic_low(opposing_traf), self.time_low(time))
        lml = min(self.traffic_low(current_traf), self.traffic_med(opposing_traf), self.time_low(time)) #
        mml = min(self.traffic_med(current_traf), self.traffic_med(opposing_traf), self.time_low(time))
        hml = min(self.traffic_hig(current_traf), self.traffic_med(opposing_traf), self.time_low(time))
        lhl = min(self.traffic_low(current_traf), self.traffic_hig(opposing_traf), self.time_low(time)) #
        mhl = min(self.traffic_med(current_traf), self.traffic_hig(opposing_traf), self.time_low(time)) #
        hhl = min(self.traffic_hig(current_traf), self.traffic_hig(opposing_traf), self.time_low(time))
        #
        llm = min(self.traffic_low(current_traf), self.traffic_low(opposing_traf), self.time_med(time)) #
        mlm = min(self.traffic_med(current_traf), self.traffic_low(opposing_traf), self.time_med(time))
        hlm = min(self.traffic_hig(current_traf), self.traffic_low(opposing_traf), self.time_med(time))
        lmm = min(self.traffic_low(current_traf), self.traffic_med(opposing_traf), self.time_med(time)) #
        mmm = min(self.traffic_med(current_traf), self.traffic_med(opposing_traf), self.time_med(time)) #
        hmm = min(self.traffic_hig(current_traf), self.traffic_med(opposing_traf), self.time_med(time))
        lhm = min(self.traffic_low(current_traf), self.traffic_hig(opposing_traf), self.time_med(time)) #
        mhm = min(self.traffic_med(current_traf), self.traffic_hig(opposing_traf), self.time_med(time)) #
        hhm = min(self.traffic_hig(current_traf), self.traffic_hig(opposing_traf), self.time_med(time))
        #
        llh = min(self.traffic_low(current_traf), self.traffic_low(opposing_traf), self.time_hig(time)) #
        mlh = min(self.traffic_med(current_traf), self.traffic_low(opposing_traf), self.time_hig(time)) #
        hlh = min(self.traffic_hig(current_traf), self.traffic_low(opposing_traf), self.time_hig(time)) #
        lmh = min(self.traffic_low(current_traf), self.traffic_med(opposing_traf), self.time_hig(time)) #
        mmh = min(self.traffic_med(current_traf), self.traffic_med(opposing_traf), self.time_hig(time)) #
        hmh = min(self.traffic_hig(current_traf), self.traffic_med(opposing_traf), self.time_hig(time)) #
        lhh = min(self.traffic_low(current_traf), self.traffic_hig(opposing_traf), self.time_hig(time)) #
        mhh = min(self.traffic_med(current_traf), self.traffic_hig(opposing_traf), self.time_hig(time)) #
        hhh = min(self.traffic_hig(current_traf), self.traffic_hig(opposing_traf), self.time_hig(time)) 
        
        do = max(lll, lml, lhl, mhl, llm, lmm, mmm, lhm, mhm, llh, mlh, hlh, lmh, mmh, hmh, lhh, mhh)
        dont = max(mll, hll, mll, hml, hhl, mlm, hlm, hmm, hhm, hhh)
        print "do:", do, "dont:", dont
        return (do > dont)        

    def run(self):
        order = [("we", "ew"), ("ns", "sn")]
        o_cnt = 0
        old = 1
        green_time = 0
        while True:
            current_traffic = len(self.junctions[order[o_cnt][0]].queue) + len(self.junctions[order[o_cnt][1]].queue) +\
                self.junctions[order[o_cnt][0]].count + self.junctions[order[o_cnt][1]].count
            opposing_traffic = len(self.junctions[order[old][0]].queue) + len(self.junctions[order[old][1]].queue) +\
                self.junctions[order[old][0]].count + self.junctions[order[old][1]].count

            print current_traffic, opposing_traffic
            if (self.fuzzySwitch(green_time, current_traffic, opposing_traffic) or green_time >= self.max_green_time) and (green_time >= 5):
                print "switching", green_time
                old = o_cnt
                o_cnt = (o_cnt + 1) % len(order)
                #yield self.env.timeout(self.loop_time)  # cekani s rozsvicenymi svetly
                # zastaveni jednoho smeru
                self.traffic_lights[order[old][0]].state = "red"
                self.traffic_lights[order[old][1]].state = "red"
                yield self.env.timeout(self.offset_time)  # offset pro dojezd aut
                # pusteni druheho smeru
                self.traffic_lights[order[o_cnt][0]].state = "green"
                self.traffic_lights[order[o_cnt][1]].state = "green"
                # spusti se udalosti tech, co cekali na cervenou
                self.traffic_lights[order[o_cnt][0]].switch_event.succeed()
                self.traffic_lights[order[o_cnt][0]].switch_event = self.env.event()
                self.traffic_lights[order[o_cnt][1]].switch_event.succeed()
                self.traffic_lights[order[o_cnt][1]].switch_event = self.env.event()
                green_time = 0
            else:
                green_time += 1

            yield self.env.timeout(1)


def main(running_time):
    global served, counter, waited_average
    env = simpy.Environment()

    # semafory z jednotlivych smeru
    tl_we = TrafficLight(env, "we", "green")
    tl_ew = TrafficLight(env, "ew", "green")
    tl_ns = TrafficLight(env, "ns", "red")
    tl_sn = TrafficLight(env, "sn", "red")

    # fronta na prvni misto
    j_we = simpy.Resource(env, capacity=1)
    j_ew = simpy.Resource(env, capacity=1)
    j_ns = simpy.Resource(env, capacity=1)
    j_sn = simpy.Resource(env, capacity=1)

    tls = {"we": tl_we, "ew": tl_ew, "ns": tl_ns, "sn": tl_sn}
    js = {"we": j_we, "ew": j_ew, "ns": j_ns, "sn": j_sn}
    # rizeni prepinani semaforu
    #TimedControlLogic(env, int(sys.argv[2]), 5, tls, js)

    FuzzyControlLogic2(env, int(sys.argv[2]), 5, tls, js)
    
    # generovani prijezdu aut
    lambda_we = 10
    lambda_ns = 40

    env.process(car_generator(env, lambda_we, j_we, tl_we, "we"))
    env.process(car_generator(env, lambda_we, j_ew, tl_ew, "ew"))
    env.process(car_generator(env, lambda_ns, j_ns, tl_ns, "ns"))
    env.process(car_generator(env, lambda_ns, j_sn, tl_sn, "sn"))

    # sbirani statistik o simulaci
    env.process(monitor(env, 60, j_we, j_ew, j_ns, j_sn))

    env.run(until=running_time)

    plot_data(running_time)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print "%s running_time in hours" % sys.argv[0]
    else:
        main(int(sys.argv[1])*3600)

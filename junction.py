#!/usr/bin/env python

import sys
import simpy
import simpy.rt
import random

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d







def m_low(var):
    if var > 10:
        return 0.0
    else:
        return (-1/10.0)*var + 1


def m_middle(var):
    if var < 5 or var > 35:
        return 0.0

    if 5 <= var < 20:
        return (1/15.0)*var - (1/3.0)

    if 20 <= var <= 35:
        return (-1/15.0)*var + (7/3.0)


def m_high(var):
    if var < 30:
        return 0.0

    if var > 40:
        return 1.0

    if 30 <= var <= 40:
        return (1/10.0)*var - (3.0)




class Fuzzy(object):
    def __init__(self, var):
        self.var = var
        self.L = m_low(var)
        self.M = m_middle(var)
        self.H = m_high(var)


def NOT(v):
    return 1-v

def AND(*args):
    return min(args)


def decide(aktualni, vedlejsi):
    if(aktualni == 0 and vedlejsi == 0):
        return False

    X = Fuzzy(aktualni)
    Y = Fuzzy(vedlejsi)
    R = Fuzzy(5*(1.0*vedlejsi/aktualni if aktualni!=0 else 9999)) #fixme

    F = []
    T = []

    F.append(R.L)
    T.append(R.M)
    T.append(R.H)

    """
    F.append(X.H)
    T.append(AND(X.L, NOT(Y.L)))
    F.append(AND(X.M, NOT(Y.H)))
    T.append(AND(X.M, Y.H))
    """

    return max(F) < max(T)

def dlouhy_interval(aktualni, vedlejsi):
    kratky = []
    dlouhy = []

    X = Fuzzy(aktualni)
    Y = Fuzzy(vedlejsi)

    kratky.append(X.L)
    kratky.append(NOT(Y.L))
    dlouhy.append(X.H)
    dlouhy.append(Y.L)

    return max(dlouhy) > max(kratky)




verbose = False
pretty_print = False

counter = 0
counter_last = 0
served = 0
served_last = 0
waited_average = 0
queue_wa = {"we": (0, 0), "ew": (0, 0), "ns": (0, 0), "sn": (0, 0)}

karlova = None
j_karlova = None
# za 24 hodin:
# 5500 aut tezkych/nakladnich (20m na auto)
# 32000 aut osobnich (6m na auto)
# 500m, 2 pruhy --> kapacita 125 aut
j_karlova_capacity = 125
k_c = 0
k_p_c = 0

monitor_data = []

start_hour = 0
#day_coef = [0.05,0.01,0.01,0.05,0.1,0.5,1.0,2.0,3.0,3.5,2.0,1.0,1.0,1.5,2.0,3.0,3.5,3.0,2.0,1.0,0.75,0.5,0.25,0.1]
day_coef = [0.05,0.01,0.01,0.05,0.1,0.5,1.0,2.0,3.0,3.5,2.5,2.2,2.0,2.2,2.5,3.0,3.5,3.0,2.0,1.0,0.75,0.5,0.25,0.1]
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
        global k_c, k_p_c
        if verbose:
            print '%d: %d arrived, will go %s' % (self.env.now, self.i, self.direction)

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
                if verbose:
                    print '%d: %d is waiting for green' % (self.env.now, self.i)

                if self.traffic_light.state == "green" and (self.direction != "we" or len(j_karlova.queue) < j_karlova_capacity):
                    #jestli je zelena, tak pokracuje bez cekani (nerozjizdi se, jede dal)
                    break
                else:
                    if self.direction == "we" and self.traffic_light.state == "green":
                        #ma zelenou, ale chce pokracovat smer karlova, ktery je plny
                        yield self.traffic_light.switch_event
                    else:
                        #ceka na semaforu
                        yield self.env.process(self.traffic_light.wait()) 
                        #chvili trva nez se rozjede
                        yield self.env.timeout(random.uniform(1.1, 2))

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

        if self.direction == "we" and False:
            with j_karlova.request() as req:
                yield req
                yield self.env.timeout(random.uniform(1.1, 2))
                while True:
                    if karlova.state == "green":
                        break
                    else:
                        yield self.env.process(karlova.wait())
                        yield self.env.timeout(random.uniform(1.1, 2))


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
            #yield self.env.timeout(self.starting)  # X sekund trva rozjizdeni aut
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

            #yield self.env.timeout(self.light_time*(0.5+day_coef[hour]))  # cekani s rozsvicenymi svetly
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


class FuzzyControlLogic2(object):
    def __init__(self, env, light_time, offset_time, tl_we, tl_ew, tl_ns, tl_sn):
        self.env = env
        self.traffic_lights = {"we": tl_we, "ew": tl_ew, "ns": tl_ns, "sn": tl_sn}
        self.action = env.process(self.run())
        self.light_time = light_time
        self.offset_time = offset_time
        #constants for traffic
        self.low_traf_max = 5
        self.med_traf_min = 3
        self.med_traf_max = 8
        self.hig_traf_min = 10
        self.hig_traf_max = 12
        #time constants
        self.low_time_max = 5
        self.med_time_min = 3
        self.med_time_max = 8
        self.hig_time_min = 10
        self.hig_time_max = 12

    #traffic functions
    def traffic_low(self, traffic):
        return max(((-traffic) / self.low_traf_max) + 1, 0)
    
    def traffic_med(self, traffic):
        if(traffic < ((self.med_traf_min + self.med_traf_max) / 2)):
            return max(0, ( traffic - self.med_traf_min) / ((self.med_traf_max - self.med_traf_min) / 2))
        else:
            return max(0, (-traffic + self.med_traf_max) / ((self.med_traf_max - self.med_traf_min) / 2))
    
    def traffic_hig(self, traffic):
        if(traffic < self.high_traf_max):
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

    def fuzzyCalculator(self, time, current_traf, opposing_traf):
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
        return (do > dont)        

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

class FuzzyControlLogic(object):
    def __init__(self, env, light_time, offset_time, tl_we, tl_ew, tl_ns, tl_sn, j_we, j_ew, j_ns, j_sn):
        self.env = env
        self.traffic_lights = {"we": tl_we, "ew": tl_ew, "ns": tl_ns, "sn": tl_sn}
        self.junctions = {"we": j_we, "ew": j_ew, "ns": j_ns, "sn": j_sn}
        self.action = env.process(self.run())
        self.offset_time = offset_time

    def run(self):
        global verbose
        order = [("we", "ew"), ("ns", "sn")]
        o_cnt = 0
        old = 1
        while True:

            aktualni = len(self.junctions[order[o_cnt][0]].queue) + len(self.junctions[order[o_cnt][1]].queue) + self.junctions[order[o_cnt][0]].count + self.junctions[order[o_cnt][1]].count
            vedlejsi = len(self.junctions[order[old][0]].queue) + len(self.junctions[order[old][1]].queue) + self.junctions[order[old][0]].count + self.junctions[order[old][1]].count

            interval___ = 30 if dlouhy_interval(aktualni, vedlejsi) else 5
            print aktualni, vedlejsi, interval___

            if decide(aktualni, vedlejsi):
                print "preblikavam"
                old = o_cnt
                o_cnt = (o_cnt + 1) % len(order)

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

            yield self.env.timeout(5)


class TimdeControlLogicKarlova(object):
    def __init__(self, env, light_time, tl):
        self.env = env
        self.tl = tl
        self.action = env.process(self.run())
        self.light_time = light_time

    def run(self):
        cnt = 0
        color = ("green", "red")
        #color = ("red", "red")
        while True:
            yield self.env.timeout(self.light_time)
            self.tl.state = color[cnt]
            if (self.tl.state == "green"):
                self.tl.switch_event.succeed()
                self.tl.switch_event = self.env.event()
            cnt = (cnt+1)%2





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
            """
            print "%d %.1f %.1f %d %d %d %d" % (
                env.now, ((s / float(c) * 100) if c != 0 else 0), (waited_average / float(served)) if served != 0 else 0,
                len(j_we.queue), len(j_ew.queue), len(j_ns.queue), len(j_sn.queue)
            )
            """
            pass
            

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
    plt.grid()

    plt.subplot(312)
    plt.plot(np.array(range(0,running_time, 600))/60, np.array(waited_average_actual)/60.0)
    plt.ylabel('average waiting time')
    plt.grid()

    plt.subplot(313)
    plt.plot(time, cars)
    plt.ylabel('cars arrived')    
    plt.grid()

    plt.show()



def main(running_time):
    global served, counter, waited_average, j_karlova, karlova
    env = simpy.Environment()
    # env = simpy.rt.RealtimeEnvironment(factor=2.0)

    # semafory z jednotlivych smeru
    tl_we = TrafficLight(env, "we", "green")
    tl_ew = TrafficLight(env, "ew", "green")
    tl_ns = TrafficLight(env, "ns", "red")
    tl_sn = TrafficLight(env, "sn", "red")

    karlova = TrafficLight(env, "karlova", "red")

    # fronta na prvni misto
    j_we = simpy.Resource(env, capacity=1)
    j_ew = simpy.Resource(env, capacity=1)
    j_ns = simpy.Resource(env, capacity=1)
    j_sn = simpy.Resource(env, capacity=1)
    j_karlova = simpy.Resource(env, capacity=1)

    # rizeni prepinani semaforu
    #TimedControlLogic(env, int(sys.argv[2]), 5, tl_we, tl_ew, tl_ns, tl_sn)

    FuzzyControlLogic(env, int(sys.argv[2]), 5, tl_we, tl_ew, tl_ns, tl_sn, j_we, j_ew, j_ns, j_sn)
    

    TimdeControlLogicKarlova(env, int(sys.argv[2]), karlova)


    # generovani prijezdu aut
    podivny_parametr_we = 10
    podivny_parametr_ns = 40

    env.process(car_generator(env, podivny_parametr_we, j_we, tl_we, "we"))
    env.process(car_generator(env, podivny_parametr_we, j_ew, tl_ew, "ew"))
    env.process(car_generator(env, podivny_parametr_ns, j_ns, tl_ns, "ns"))
    env.process(car_generator(env, podivny_parametr_ns, j_sn, tl_sn, "sn"))

    # sbirani statistik o simulaci
    env.process(monitor(env, 60, j_we, j_ew, j_ns, j_sn))

    env.run(until=running_time)

    print "projelo: %d" % (counter)
    plot_data(running_time)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print "%s running_time in hours" % sys.argv[0]
    else:
        main(int(sys.argv[1])*3600)
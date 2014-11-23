#!/usr/bin/env python

import sys
import simpy
import simpy.rt
import random

verbose = False
pretty_print = False

counter = 0
served = 0
waited_average = 0
queue = {"we": 0, "ew": 0, "ns": 0, "sn": 0}


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
        global served, verbose, waited_average, queue
        if verbose:
            print '%d: %d arrived, will go %s' % (self.env.now, self.i, self.direction)

        started = self.env.now
        queue[self.direction] += 1

        # fronta na prvni misto u semaforu
        # de fakto jenom tupe stoji ve fronte a teprve az se dostane do junction,
        # tak se diva, jestli muze jet nebo ne
        with self.junction.request() as req:
            yield req  # cekani na prvni misto

            if verbose:
                print '%d: %d is waiting for green' % (self.env.now, self.i)
            yield self.env.process(self.traffic_light.wait())  # cekani na zelenou na semaforu
            if verbose:
                print '%d: %d is free to go %s' % (self.env.now, self.i, self.direction)

            waited_average += self.env.now - started
            queue[self.direction] -= 1

            yield self.env.timeout(self.going_through_time)  # doba prujezdu krizovatkou
            if verbose:
                print '%d: %d passed junction going %s' % (self.env.now, self.i, self.direction)
            served += 1


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
    def __init__(self, env, wait_time, tl_we, tl_ew, tl_ns, tl_sn):
        self.env = env
        self.traffic_lights = {"we": tl_we, "ew": tl_ew, "ns": tl_ns, "sn": tl_sn}
        self.action = env.process(self.run())
        self.wait_time = wait_time

    def run(self):
        global verbose
        order = [("we", "ew"), ("ns", "sn")]
        o_cnt = 0
        while True:
            yield self.env.timeout(self.wait_time)  # cekani na prepnuti semaforu
            old = o_cnt
            o_cnt = (o_cnt + 1) % len(order)
            if verbose:
                print '%d: %s are good to go' % (self.env.now, " and ".join(order[o_cnt]))
            # prepnou se barvy semaforu
            self.traffic_lights[order[old][0]].state = "red"
            self.traffic_lights[order[old][1]].state = "red"
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
        # vygeneruju auto
        Car(env, junction, traffic_light, counter, direction)
        counter += 1
        # uspim se na nejakou dobu
        yield env.timeout(random.expovariate(1.0 / interval))


def monitor(env, interval):
    global served, counter, waited_average, queue
    while True:
        if pretty_print:
            print "-------------------------"
            print "On %d:" % env.now
            print "Served: %d cars from %d (%.1f %%)" % (served, counter, (served / float(counter) * 100))
            print "Average waiting time: %f" % ((waited_average / float(served)) if served != 0 else 0)
            print "Queue count: %d %d %d %d" % (queue["we"], queue["ew"], queue["ns"], queue["sn"])
        else:
            print "%d %.1f %f %d %d %d %d" % (
                env.now, (served / float(counter) * 100), (waited_average / float(served)) if served != 0 else 0,
                queue["we"], queue["ew"], queue["ns"], queue["sn"]
            )
        yield env.timeout(interval)


def main(running_time):
    global served, counter, waited_average
    env = simpy.Environment()
    # env = simpy.rt.RealtimeEnvironment()

    # semafory z jednotlivych smeru
    tl_we = TrafficLight(env, "we", "green", 2)
    tl_ew = TrafficLight(env, "ew", "green", 2)
    tl_ns = TrafficLight(env, "ns", "red", 2)
    tl_sn = TrafficLight(env, "sn", "red", 2)
    # rizeni prepinani semaforu
    TimedControlLogic(env, 30, tl_we, tl_ew, tl_ns, tl_sn)

    # fronta na prvni misto
    j_we = simpy.Resource(env, capacity=1)
    j_ew = simpy.Resource(env, capacity=1)
    j_ns = simpy.Resource(env, capacity=1)
    j_sn = simpy.Resource(env, capacity=1)

    # generovani prijezdu aut
    env.process(car_generator(env, 15, j_we, tl_we, "we"))
    env.process(car_generator(env, 15, j_ew, tl_ew, "ew"))
    env.process(car_generator(env, 15, j_ns, tl_ns, "ns"))
    env.process(car_generator(env, 15, j_sn, tl_sn, "sn"))

    # sbirani statistik o simulaci
    env.process(monitor(env, 60))

    env.run(until=running_time)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print "%s running_time" % sys.argv[0]
    else:
        main(int(sys.argv[1]))
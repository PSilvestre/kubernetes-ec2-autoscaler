import datetime
from abc import abstractmethod
import time
import autoscaler.autoscaling_groups as autoscaling_groups
import autoscaler.azure as azure
from autoscaler.azure_api import AzureWriteThroughCachedApi, AzureWrapper
import autoscaler.capacity as capacity
from autoscaler.kube import KubePod, KubeNode, KubeResource, KubePodStatus
import autoscaler.utils as utils
import logging
import json
from azure.mgmt.resource.resources import ResourceManagementClient
from azure.common.credentials import ServicePrincipalCredentials
from msrestazure.azure_exceptions import CloudError
from autoscaler.config import Config

logger = logging.getLogger(__name__)


# Abstract class that represents a scaling policy. Also handles the logic necessary to perform the scaling
class ScalingPolicy:
    def __init__(self):
        pass
        # Do nothing

    def fulfill_requests(self, async_operations):
        for operation in async_operations:
            try:
                operation.result()
            except CloudError as e:
                logger.warn("Error while scaling Scale Set: {}".format(e.message))
            except TimeoutError:
                logger.warn("Timeout while scaling Scale Set")

    def create_async_operation(self, cluster, group, assigned_pods, new_capacity, units_requested):
        async_operation = group.scale(new_capacity)

        def notify_if_scaled(future):
            if future.result():
                flat_assigned_pods = []
                for instance_pods in assigned_pods:
                    flat_assigned_pods.extend(instance_pods)
                    cluster.notifier.notify_scale(group, units_requested, flat_assigned_pods)

        async_operation.add_done_callback(notify_if_scaled)
        return async_operation

    def apply(self, pending_pods, asgs, cluster):
        async_operations = []
        for selectors_hash in set(pending_pods.keys()):
            self.decide_num_instances(cluster, pending_pods, asgs, async_operations)
        self.fulfill_requests(async_operations)

    def decide_num_instances(self, cluster, pending_pods, asgs, async_operations):
        # scale each node type to reach the new capacity
        for selectors_hash in set(pending_pods.keys()):
            pods = pending_pods.get(selectors_hash, [])
            accounted_pods = dict((p, False) for p in pods)
            num_unaccounted = len(pods)

            groups = utils.get_groups_for_hash(asgs, selectors_hash)

            groups = cluster._prioritize_groups(groups)

            for group in groups:
                if (cluster.autoscaling_timeouts.is_timed_out(
                        group) or group.is_timed_out() or group.max_size == group.desired_capacity) \
                        and not group.unschedulable_nodes:
                    continue

                unit_capacity = capacity.get_unit_capacity(group)
                new_instance_resources = []
                assigned_pods = []
                for pod, acc in accounted_pods.items():
                    if acc or not (unit_capacity - pod.resources).possible or not group.is_taints_tolerated(pod):
                        continue

                    found_fit = False
                    for i, instance in enumerate(new_instance_resources):
                        if (instance - pod.resources).possible:
                            new_instance_resources[i] = instance - pod.resources
                            assigned_pods[i].append(pod)
                            found_fit = True
                            break
                    if not found_fit:
                        new_instance_resources.append(
                            unit_capacity - pod.resources)
                        assigned_pods.append([pod])

                # new desired # machines = # running nodes + # machines required to fit jobs that don't
                # fit on running nodes. This scaling is conservative but won't
                # create starving
                units_needed = len(new_instance_resources)
                # The pods may not fit because of resource requests or taints. Don't scale in that case
                if units_needed == 0:
                    continue
                units_needed += cluster.over_provision

                if cluster.autoscaling_timeouts.is_timed_out(group) or group.is_timed_out():
                    # if a machine is timed out, it cannot be scaled further
                    # just account for its current capacity (it may have more
                    # being launched, but we're being conservative)
                    unavailable_units = max(
                        0, units_needed - (group.desired_capacity - group.actual_capacity))
                else:
                    unavailable_units = max(
                        0, units_needed - (group.max_size - group.actual_capacity))
                units_requested = units_needed - unavailable_units

                new_capacity = group.actual_capacity + units_requested

                async_operations.append(
                    self.create_async_operation(cluster, group, assigned_pods, new_capacity, units_requested))


class BasicScalingPolicy(ScalingPolicy):
    def __init__(self):
        ScalingPolicy.__init__(self)

class CostBasedScalingPolicy(ScalingPolicy):
    def __init__(self, max_cost_per_hour, region):
        ScalingPolicy.__init__(self)
        self.max_cost_per_hour = max_cost_per_hour
        self.region = region
        self.start_time = time.time()
        self.num_hours = 0
        self.spent_this_hour = 0
        self.num_seconds_instances_used = 0
        self.num_instances_tracked = 0

        with open(Config.COST_DATA, 'r') as f:
            data = json.loads(f.read())
            for json_region, region_data in data.items():
                if region_data['name'] == self.region:
                    self.costs_per_hour = region_data['costs-per-hour']

    def apply(self, pending_pods, asgs, cluster):
        async_operations = []
        avg_hours_used_per_instance = 0.25

        if self.num_instances_tracked > 0:
            avg_hours_used_per_instance = self.num_seconds_instances_used / self.num_instances_tracked / 3600
        logger.info('Cost Based Policy Stats:    Hours: ' + str(self.num_hours) + ' max per hour: ' + str(self.max_cost_per_hour) + ' spent this hour: ' + str(self.spent_this_hour)
                     + ' avg duration: ' + str(avg_hours_used_per_instance))
        for selectors_hash in set(pending_pods.keys()):
            self.decide_num_instances(cluster, pending_pods, asgs, async_operations)
        self.fulfill_requests(async_operations)

    def node_terminated(self, creation_time, instance_type):
        creation_time_epoch = (creation_time.replace(tzinfo=None) - datetime.datetime(1970,1,1)).total_seconds()
        time_used_by_instance = (time.time() - creation_time_epoch)
        self.num_seconds_instances_used += time_used_by_instance
        self.num_instances_tracked += 1
        # cost of instance type * num hours used
        self.spent_this_hour += self.costs_per_hour[instance_type]['cost-per-hour'] * (time_used_by_instance / 3600)


    def decide_num_instances(self, cluster, pending_pods, asgs, async_operations):
        curr_time = time.time()
        if (self.start_time - curr_time) / 3600 > self.num_hours: # If started a new hour, start new count
            self.num_hours += 1
            self.spent_this_hour = 0


        # scale each node type to reach the new capacity
        for selectors_hash in set(pending_pods.keys()):
            pods = pending_pods.get(selectors_hash, [])
            accounted_pods = dict((p, False) for p in pods)
            num_unaccounted = len(pods)

            groups = utils.get_groups_for_hash(asgs, selectors_hash)

            groups = cluster._prioritize_groups(groups)

            for group in groups:
                if (cluster.autoscaling_timeouts.is_timed_out(
                        group) or group.is_timed_out() or group.max_size == group.desired_capacity) \
                        and not group.unschedulable_nodes:
                    continue

                unit_capacity = capacity.get_unit_capacity(group)
                new_instance_resources = []
                assigned_pods = []
                for pod, acc in accounted_pods.items():
                    if acc or not (unit_capacity - pod.resources).possible or not group.is_taints_tolerated(pod):
                        continue

                    found_fit = False
                    for i, instance in enumerate(new_instance_resources):
                        if (instance - pod.resources).possible:
                            new_instance_resources[i] = instance - pod.resources
                            assigned_pods[i].append(pod)
                            found_fit = True
                            break
                    if not found_fit:
                        new_instance_resources.append(
                            unit_capacity - pod.resources)
                        assigned_pods.append([pod])

                # new desired # machines = # running nodes + # machines required to fit jobs that don't
                # fit on running nodes. This scaling is conservative but won't
                # create starving
                units_needed = len(new_instance_resources)
                # The pods may not fit because of resource requests or taints. Don't scale in that case
                if units_needed == 0:
                    continue
                units_needed += cluster.over_provision

                if cluster.autoscaling_timeouts.is_timed_out(group) or group.is_timed_out():
                    # if a machine is timed out, it cannot be scaled further
                    # just account for its current capacity (it may have more
                    # being launched, but we're being conservative)
                    unavailable_units = max(
                        0, units_needed - (group.desired_capacity - group.actual_capacity))
                else:
                    unavailable_units = max(
                        0, units_needed - (group.max_size - group.actual_capacity))
                units_requested = units_needed - unavailable_units

                avg_hours_used_per_instance = 0.25

                if self.num_instances_tracked > 0:
                    avg_hours_used_per_instance = self.num_seconds_instances_used / self.num_instances_tracked / 3600
                # If we've used 75% of budget stop provisioning. No guarantees we wont go over budget,
                # but conservative enough for most uses.

                for i in range(units_requested):
                    predicted_cost = self.spent_this_hour + (i + 1) * avg_hours_used_per_instance * self.costs_per_hour[group.instance_type]['cost-per-hour']
                    if predicted_cost > self.max_cost_per_hour * 0.75:
                        units_requested = i + 1
                        break

                new_capacity = group.actual_capacity + units_requested


                async_operations.append(
                    self.create_async_operation(cluster, group, assigned_pods, new_capacity, units_requested))


class GrowthBasedScalingPolicy(ScalingPolicy):

    def __init__(self, trigger_growth_factor, num_triggers_to_provision):
        ScalingPolicy.__init__(self)
        self.trigger_growth_factor = trigger_growth_factor
        self.num_triggers_to_provision = num_triggers_to_provision
        self.num_triggers = 0
        self.last_num_pods = 0;

    def apply(self, pending_pods, asgs, cluster):
        num_pending_pods = sum(len(podlist) for podlist in pending_pods.values())
        if num_pending_pods > self.trigger_growth_factor * self.last_num_pods:
            self.num_triggers += 1
            self.last_num_pods = num_pending_pods
        else:
            if num_pending_pods < self.last_num_pods * 0.75:
                self.num_triggers = 0
                self.last_num_pods = 0;
        logger.info(
            'Growth Based Policy Stats:    num_triggers_to_provision: ' + str(self.num_triggers_to_provision) + ' trigger_growth_factor: '
            + str(self.trigger_growth_factor) + ' num_triggers: ' + str(self.num_triggers) + ' last_num_pods: ' + str(self.last_num_pods) + ' curr_num_pods: ' + str(num_pending_pods))
        if self.num_triggers >= self.num_triggers_to_provision:
            self.num_triggers = 0
            self.last_num_pods = 0;
            async_operations = []
            logger.info('Growth Based Policy Trigger! Growing Cluster!')
            for selectors_hash in set(pending_pods.keys()):
                self.decide_num_instances(cluster, pending_pods, asgs, async_operations)
            self.fulfill_requests(async_operations)
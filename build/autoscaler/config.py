import os


class Config(object):
    CAPACITY_DATA = os.environ.get('CAPACITY_DATA', 'data/capacity.json')
    CAPACITY_CPU_RESERVE = float(os.environ.get('CAPACITY_CPU_RESERVE', 0.0))
    COST_DATA = os.environ.get('COST_DATA', 'data/costs.json')
    NAMESPACE = os.environ.get('NAMESPACE', 'system')

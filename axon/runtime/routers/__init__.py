# axon/runtime/routers/__init__.py
"""
Routers module for Model Execution Kernel (MEK).
Provides Bayesian and active inference capability routing.
"""

from .bayesian_selector import BayesianRouter

__all__ = ["BayesianRouter"]

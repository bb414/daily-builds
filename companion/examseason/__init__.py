"""Exam season: turn an exam timetable, topics and your free time into a revision plan.

The model (model.py) mirrors the browser app's model exactly; the rest of the
package adds what a browser is not good at: a study-group planner, a morning
re-plan job, HTML reports and a command-line interface (cli.py).
"""

from .model import *  # noqa: F401,F403
from .model import VERSION  # noqa: F401
from .samples import member_project, sample_project  # noqa: F401

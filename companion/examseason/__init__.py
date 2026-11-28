"""Exam season: turn an exam timetable, topics and your free time into a revision plan.

The model (model.py) mirrors the browser app's model exactly; the rest of the
package adds what a browser is not good at: a study-group planner (group.py),
HTML reports (report.py) and a command-line interface with the morning re-plan
job (cli.py).
"""

from . import model
from .samples import member_project, sample_project

__all__ = ['model', 'member_project', 'sample_project']

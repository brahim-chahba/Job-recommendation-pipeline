import pandas as pd

from sources.jobspy_common import scrape_jobspy_site


def scrape(results_wanted: int = 20) -> pd.DataFrame:
    return scrape_jobspy_site("indeed", results_wanted=results_wanted)

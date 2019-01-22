# -*- coding: utf8 -*-

import sys
import os
import math

import xarray as xr
import scipy.stats
import numpy as np

import ev_fit


def KS_test(ecdf, cdf):
    """Retun the Kolmogorov–Smirnov test statistic
    """
    return np.abs(ecdf-cdf).max(dim='year')


def KS_Dcrit(ds, chunks):
    """Estimate the critical values of the KS test.
    Use the pool of KS stats calculated over the whole dataset.
    The critical value corresponds to the quantile all the KS stats.

    See also:
    Wilks, D. S. (2011).
    Frequentist Statistical Inference.
    International Geophysics, 100, 133–186.
    https://doi.org/10.1016/B978-0-12-385022-5.00005-1
    """
    significance_levels = [0.01, 0.05, 0.1, 0.2, 0.4]
    q_levels = [1-i for i in significance_levels]
    # quantile does not work for arrays stored as dask arrays
    ks_d = ds['KS_D'].load().quantile(q_levels).values
    ds['Dcrit'] = xr.DataArray(ks_d, name='Dcrit',
                               coords=[significance_levels],
                               dims=['significance_level'])
    return ds.chunk(chunks)


# def anderson_gumbel(x):
#     try:
#         return scipy.stats.anderson(x, dist='gumbel_r')[0]
#     except RuntimeError:
#         return np.nan


# def anderson_darling(ds):
#     """
#     """
#     # Get the critical values (depend only on the sample length)
#     _, critical_values, significance_levels = scipy.stats.anderson(ds['year'], dist='gumbel_r')
#     da_critical_values = xr.DataArray(critical_values, name='A2_crit',
#                                       coords=[significance_levels],
#                                       dims=['significance_level'])
#     # Goodness of fit of the Gumbel distribution
#     da_a2 = xr.apply_ufunc(anderson_gumbel,
#                            ds['annual_max'],
#                            input_core_dims=[['year']],
#                            vectorize=True,
#                            dask='parallelized',
#                            output_dtypes=[DTYPE]
#                            ).rename('A2')
#     return da_critical_values, da_a2
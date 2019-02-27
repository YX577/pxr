# -*- coding: utf8 -*-
import sys
import os
from datetime import datetime, timedelta
import csv
import math

import numpy as np
import xarray as xr
import dask
from dask.diagnostics import ProgressBar, Profiler, ResourceProfiler, CacheProfiler
from dask.distributed import Client, LocalCluster
import zarr
import scipy.stats

from bokeh.io import export_png

import ev_fit
import gof
import helper
import bootstrap
import ufuncs


DATA_DIR = '/home/lunet/gylc4/geodata/ERA5/'
# DATA_DIR = '../data/MIDAS/'
# HOURLY_FILE1 = 'midas_2000-2017_precip_pairs.nc'
HOURLY_FILE = 'era5_1979-2018_precip.zarr'

AMS_FILE = 'era5_1979-2018_ams.zarr'
ANNUAL_FILE_BASENAME = 'era5_1979-2018_ams_{}.zarr'
# ANNUAL_FILE_GRADIENT = 'era5_2000-2017_precip_gradient.zarr'
# ANNUAL_FILE_SCALING = 'midas_2000-2017_precip_pairs_scaling.nc'

LOG_FILENAME = 'Analysis_log_{}.csv'.format(str(datetime.now()))

# Extract
# EXTRACT = dict(latitude=slice(1.0, -0.25),
#                longitude=slice(32.5, 35))
EXTRACT = dict(latitude=slice(90, 45),
               longitude=slice(0, 45))

# Event durations in hours - has to be adjusted to temporal resolution for the moving window
# Selected to be equally spaced on a log scale. Manually adjusted from a call to np.geomspace()
DURATIONS_SUBDAILY = [1, 2, 3, 4, 6, 8, 10, 12, 18, 24]
DURATIONS_DAILY = [24, 48, 72, 96, 120, 144, 192, 240, 288, 360]
# use fromkeys to remove duplicate. need py >= 3.6 to preserve order
DURATIONS_ALL = list(dict.fromkeys(DURATIONS_SUBDAILY + DURATIONS_DAILY))

DURATION_DICT = {'all': DURATIONS_ALL, 'daily': DURATIONS_DAILY, 'subdaily': DURATIONS_SUBDAILY}
# DURATION_DICT = {'daily': DURATIONS_DAILY}
# Temporal resolution of the input in hours
TEMP_RES = 1
# TEMP_RES = 24

LR_RES = ['slope', 'intercept', 'rvalue', 'pvalue', 'stderr']

DTYPE = 'float32'

HOURLY_CHUNKS = {'time': -1, 'latitude': 16, 'longitude': 16}
# 4 cells: 1 degree
ANNUAL_CHUNKS = {'year': -1, 'duration':-1, 'latitude': 30*4, 'longitude': 30*4}
# When resolution is 1 degree
ANNUAL_CHUNKS_1DEG = {'year': -1, 'duration': -1, 'latitude': 30, 'longitude': 30}
EXTRACT_CHUNKS = {'year': -1, 'duration':-1, 'latitude': 30, 'longitude': 30}
GAUGES_CHUNKS = {'year': -1, 'duration':-1, 'station': 200}
GEN_FLOAT_ENCODING = {'dtype': DTYPE, 'compressor': zarr.Blosc(cname='lz4', clevel=9)}
ANNUAL_ENCODING = {'annual_max': GEN_FLOAT_ENCODING,
                   'duration': {'dtype': DTYPE},
                   'latitude': {'dtype': DTYPE},
                   'longitude': {'dtype': DTYPE}}


def step1_annual_maxs_of_roll_mean(ds, precip_var, time_dim, durations, temp_res):
    """for each rolling windows size:
    compute the annual maximum of a moving mean
    return an array with the durations as a new dimension
    """
    da_list = []
    for duration in durations:
        window_size = int(duration / temp_res)
        precip = ds[precip_var]
        precip_roll_mean = precip.rolling(**{time_dim:window_size}, min_periods=max(int(window_size*.9), 1)).mean(dim=time_dim, skipna=True)
        annual_max = precip_roll_mean.groupby('{}.year'.format(time_dim)).max(dim=time_dim, skipna=True).rename('annual_max')
        da_list.append(annual_max)
    return xr.concat(da_list, 'duration').to_dataset().assign_coords(duration=durations)


def step11_arg_maxs_of_roll_mean(ds, precip_var, time_dim, durations, temp_res):
    """for each rolling windows size:
    compute the location of the annual maximum of a moving mean
    """
    da_list = []
    for duration in durations:
        window_size = int(duration / temp_res)
        precip = ds[precip_var]
        precip_roll_mean = precip.rolling(**{time_dim:window_size}, min_periods=max(int(window_size*.9), 1)).mean(dim=time_dim, skipna=True)
        arg_max = precip_roll_mean.groupby('{}.year'.format(time_dim)).argmax(dim=time_dim, skipna=True).rename('argmax')
        da_list.append(arg_max)
    return xr.concat(da_list, 'duration')


def step21_pole_trim(ds):
    # remove north pole to get a dividable latitude number
    lat_second = ds['latitude'][1].item()
    lat_last = ds['latitude'][-1].item()
    ds = ds.sel(latitude=slice(lat_second, lat_last))
    return(ds)


def step22_rank_ecdf(ds_ams, chunks):
    """Compute the rank of AMS and the empirical probability
    """
    n_obs = ds_ams['year'].count()
    da_ams = ds_ams['annual_max']
    da_ranks = ev_fit.rank_ams(da_ams, DTYPE)
    # Merge arrays in a single dataset, set the dask chunks
    ds = xr.merge([da_ams, da_ranks]).chunk(chunks)
    # Empirical probability
    # ds['ecdf_weibull'] = ev_fit.ecdf_weibull(ds['rank'], n_obs)
    # ds['ecdf_landwehr'] = ev_fit.ecdf_landwehr(ds['rank'], n_obs)
    ds['ecdf_goda'] = ev_fit.ecdf_goda(ds['rank'], n_obs)
    print(ds)
    return ds


def step23_fit_evs(ds):
    """Fit EV using various techniques.
    Keep them along a new dimension
    """
    models = [
        # (ev_fit.gumbel_pwm, (ds,), 'gumbel'),
        # (ev_fit.gev_pwm, (ds,), 'gev'),
        (ev_fit.frechet_pwm, (ds,), 'frechet'),
        (ev_fit.gev_pwm, (ds, -0.114), 'gev-0.114'),
        ]
    ds_list = []
    for fit_func, args, model_name in models:
        # Put the parameters in a new dimension
        param_list = []
        for da_param in fit_func(*args):
            da_param = da_param.expand_dims('ev_param')
            da_param.coords['ev_param'] = [da_param.name]
            param_list.append(da_param.rename('ev_parameter'))
        da_params = xr.concat(param_list, dim='ev_param')
        # Compute the corresponding CDF
        da_cdf = ev_fit.gev_cdf(ds['annual_max'],
                                da_params.sel(ev_param='location'),
                                da_params.sel(ev_param='scale'),
                                da_params.sel(ev_param='shape'),
                                ).rename('cdf')
        # Test whether shape is zero
        da_z = ev_fit.z_test(da_params.sel(ev_param='shape'),
                             ds['year'].count()).rename('Z_stat')
        ds_fit = xr.merge([da_params, da_cdf, da_z])
        ds_fit = ds_fit.expand_dims('ev_fit')
        ds_fit.coords['ev_fit'] = [model_name]
        ds_list.append(ds_fit)
    ds_fit = xr.concat(ds_list, dim='ev_fit')
    ds = xr.merge([ds, ds_fit])
    return ds


def step24_goodness_of_fit(ds, chunks):
    ds['KS_D'] = gof.KS_test(ds['ecdf_goda'], ds['cdf'])
    ds = gof.lilliefors_Dcrit(ds, chunks)
    return ds


def step31_ci(ds, ev_shape=0.114, n_sample=1000):
    """Estimate confidence interval using the bootstrap method
    """
    ds_bootstrap = bootstrap.ci_gev(ds, DTYPE, n_sample=n_sample, ci_range=0.9, shape=ev_shape)
    return ds_bootstrap
    # ds = bootstrap.ci_gev_direct(ds, n_sample=n_sample, ci_range=0.9, ev_shape=ev_shape, dtype=DTYPE)
    return ds


def step3_scaling(ds):
    """Take a Dataset as input containing the fitted EV parameters
    Fit a linear function on the log of the parameters and the log of the duration
    Keep the regression parameters as variables
    The fitting is done on various groups of durations kept as a new dimension
    """
    # log-transform the variables
    var_list = ['duration', 'location', 'scale']
    logvar_list = ['log_duration', 'log_location', 'log_scale']
    for var, log_var in zip(var_list, logvar_list):
        ds[log_var] = np.log10(ds[var])

    ds_list = []
    for dur_name, durations in DURATION_DICT.items():
        # Select only the durations of interest
        ds_sel = ds.sel(duration=durations)
        da_list = []
        for g_param_name in ['location', 'scale']:
            param_col = 'log_{}'.format(g_param_name)
            # Do the linear regression.
            slope, intercept, rvalue, pvalue, stderr = linregress(nanlinregress,
                                                  ds_sel['log_duration'],
                                                  ds_sel[param_col],
                                                  ['duration'])
            for var_name, da in zip(['line_slope', 'line_intercept', 'line_rvalue', 'line_pvalue', 'line_stderr'],
                                    [slope, intercept, rvalue, pvalue, stderr]):
                da.name = '{}_{}'.format(g_param_name, var_name)
                da_list.append(da)
        # Group all DataArrays in a single dataset
        ds_fit = xr.merge(da_list)
        # Keep the the results in their own dimension
        ds_fit = ds_fit.expand_dims('scaling_extent')
        ds_fit.coords['scaling_extent'] = [dur_name]
        ds_list.append(ds_fit)
    ds_fit = xr.concat(ds_list, dim='scaling_extent')
    # Add those DataArray to the general Dataset
    ds = xr.merge([ds, ds_fit])
    return ds


def main():
    # with ProgressBar(), Profiler() as prof:
    with ProgressBar():
        # Load hourly data #
        # hourly_path = os.path.join(DATA_DIR, HOURLY_FILE)
        # hourly = xr.open_zarr(hourly_path)

        # Get annual maxima #
        # annual_maxs = step1_annual_maxs_of_roll_mean(hourly1, 'prcp_amt', 'end_time', DURATIONS_ALL, TEMP_RES)#.chunk(ANNUAL_CHUNKS)
        # ams = step1_annual_maxs_of_roll_mean(hourly, 'precipitation', 'time', DURATIONS_ALL, TEMP_RES).chunk(ANNUAL_CHUNKS)
        # amax_path = os.path.join(DATA_DIR, AMS_FILE)
        # encoding = {v:GEN_FLOAT_ENCODING for v in ams.data_vars.keys()}
        # ams.to_zarr(amax_path, mode='w', encoding=encoding)

        # argmax = step11_arg_maxs_of_roll_mean(hourly, 'precipitation', 'time', DURATIONS_ALL, TEMP_RES).chunk(ANNUAL_CHUNKS).to_dataset()
        # argmax_path = os.path.join(DATA_DIR, ANNUAL_FILE_BASENAME.format('argmax'))
        # encoding = {v:GEN_FLOAT_ENCODING for v in argmax.data_vars.keys()}
        # print(argmax.load())
        # argmax.to_zarr(argmax_path, mode='w', encoding=encoding)

        # amax_path = os.path.join(DATA_DIR, AMS_FILE)
        # ams = xr.open_zarr(amax_path)
        # print(ams)

        # reshape to 1 deg
        # print(ds_trimmed)
        # ds_r = helper.da_pool(ds_trimmed['annual_max'], .25, 1).to_dataset().chunk(ANNUAL_CHUNKS_1DEG)
        # print(ds_r)

        # ams_path = os.path.join(DATA_DIR, AMS_FILE)
        # ams = xr.open_zarr(ams_path)
        # ds_trimmed = step21_pole_trim(ams1)


        # Rank # 
        # ds_ranked = step22_rank_ecdf(ams, ANNUAL_CHUNKS)
        # print(ds_ranked)
        ranked_path = os.path.join(DATA_DIR, ANNUAL_FILE_BASENAME.format('ranked'))
        # encoding = {v:GEN_FLOAT_ENCODING for v in ds_ranked.data_vars.keys()}
        # ds_ranked.to_zarr(ranked_path, mode='w', encoding=encoding)

        # fit EV #
        # ds_ranked = xr.open_zarr(ranked_path)#.loc[EXTRACT]
        # print(ds_ranked.load())
        # ds_fitted = step23_fit_ev(ds_ranked)
        # fitted_path = os.path.join(DATA_DIR, ANNUAL_FILE_BASENAME.format('fitted'))
        # encoding = {v:GEN_FLOAT_ENCODING for v in ds_fitted.data_vars.keys()}
        # ds_fitted.to_zarr(fitted_path, mode='w', encoding=encoding)
        # print(ds_fitted)

        # GoF #
        # ds_fitted = xr.open_zarr(fitted_path)
        # ds_gof = step24_goodness_of_fit(ds_fitted, ANNUAL_CHUNKS)
        # gof_path = os.path.join(DATA_DIR, ANNUAL_FILE_BASENAME.format('gof'))
        # encoding = {v:GEN_FLOAT_ENCODING for v in ds_gof.data_vars.keys()}
        # ds_gof.to_zarr(gof_path, mode='w', encoding=encoding)

        # confidence interval #
        # ds_ranked = xr.open_zarr(ranked_path).loc[EXTRACT].chunk(EXTRACT_CHUNKS)
        # ds_ranked = step21_pole_trim(ds_ranked)
        # print(ds_ranked)
        # ds_ci = step31_ci(ds_ranked, n_sample=1000)
        ci_path = os.path.join(DATA_DIR, ANNUAL_FILE_BASENAME.format('ci_extract'))
        # encoding = {v: GEN_FLOAT_ENCODING for v in ds_ci.data_vars.keys()}
        # print(ds_ci)
        # ds_ci.to_zarr(ci_path, mode='w', encoding=encoding)
        ds_ci = xr.open_zarr(ci_path)
        ci_sel = ds_ci.sel(longitude=40, latitude=50, duration=24, ev_param='location')
        print(ci_sel.load())

        # ds_fitted = xr.open_zarr(fitted_path)#.loc[EXTRACT]
        # MAE of parameters
        # ds_fitted.load()
        # ds_pwm = ds_fitted.sel(ev_fit='gev_pwm')
        # ds_mle = ds_fitted.sel(ev_fit='gev_mle')
        # shape_mae = np.abs(-ds_pwm['shape'] - ds_mle['shape']).mean()
        # scale_mae = np.abs(ds_pwm['scale'] - ds_mle['scale']).mean()
        # location_mae = np.abs(ds_pwm['location'] - ds_mle['location']).mean()
        # print(location_mae)
        # print(ds_mle['location'].mean())
        # print(scale_mae)
        # print(ds_mle['scale'].mean())
        # print(shape_mae)
        # print(ds_mle['shape'].mean())
        # print(ds_pwm['shape'].mean())

        # Profiling results
        # print(prof.results[0])
        # viz = prof.visualize()
        # print(viz)
        # print(type(viz))
        # export_png(viz, filename='profile.png')


if __name__ == "__main__":
    # Use dask distributed LocalCluster (uses processes instead of threads)
    # cluster = LocalCluster(n_workers=16, threads_per_worker=2)
    # cluster = LocalCluster()
    # print(cluster)
    # client = Client(cluster)
    sys.exit(main())

# -*- coding: utf8 -*-
import matplotlib
matplotlib.use("Agg")

import sys
import os
import datetime
import math
import itertools

import numpy as np
import xarray as xr
import pandas as pd
import geopandas as gpd
import shapely.geometry
import seaborn as sns
import cartopy as ctpy
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import matplotlib.pyplot as plt


DATA_DIR = '../data'
# HOURLY_FILE = 'era5_2000-2012_precip.zarr'
ERA_ANNUAL_FILE = 'era5_2000-2017_precip_complete.zarr'
# GAUGES_FILE = '../data/GHCN/ghcn.nc'
# GHCN_ANNUAL_FILE = '../data/GHCN/ghcn_2000-2017_precip_scaling.nc'
MIDAS_ANNUAL_FILE = '../data/MIDAS/midas_2000-2017_precip_scaling.nc'
# HADISD_ANNUAL_FILE = '../data/HadISD/hadisd_2000-2017_precip_scaling.nc'
PLOT_DIR = '../plot'

EXTRACT = dict(latitude=slice(45, -45),
               longitude=slice(0, 180))

# Coordinates of study sites
# STUDY_SITES = {'Kampala': (0.317, 32.616),
#                'Kisumu': (0.1, 34.75)}
STUDY_SITES = {'Jakarta': (-6.2, 106.816), 'Sydney': (-33.865, 151.209),
               'Beijing': (39.92, 116.38), 'New Delhi': (28.614, 77.21),
               'Nairobi': (-1.28, 36.82), 'Brussels': (50.85, 4.35),
               'Santiago': (-33.45, -70.67+360), 'New York City': (40.72, -74.0+360),
               'Mexico City': (19.43, -99.13+360)
               }

XTICKS = [1, 3, 6, 12, 24, 48, 120, 360]

# color-blind safe qualitative palette from colorbrewer2
C_PRIMARY_1 = '#1f78b4'
C_SECONDARY_1 = '#6ba9ca'
C_PRIMARY_2 = '#33a02c'
C_SECONDARY_2 = '#89c653'

def single_map(da, cbar_label, title, fig_name, center=None, reverse=False):
    """https://cbrownley.wordpress.com/2018/05/15/visualizing-global-land-temperatures-in-python-with-scrapy-xarray-and-cartopy/
    """
    plt.figure(figsize=(8, 5))
    ax_p = plt.gca(projection=ctpy.crs.Robinson(), aspect='auto')
    if center:
        if reverse:
            cmap = 'RdBu_r'
        else:
            cmap = 'RdBu'
        da.plot.imshow(ax=ax_p, transform=ctpy.crs.PlateCarree(),
                       robust=True, cmap=cmap, center=center,
                    #    add_colorbar=True,
                       cbar_kwargs=dict(orientation='horizontal', label=cbar_label))
    else:
        da.plot.imshow(ax=ax_p, transform=ctpy.crs.PlateCarree(),
                       robust=True, cmap='viridis',
                       cbar_kwargs=dict(orientation='horizontal', label=cbar_label))
    ax_p.coastlines(linewidth=.5, color='black')
    plt.title(title)
    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def multi_maps(ds, var_names, disp_names, value_name, fig_name, duration=24, sqr=False):
    crs = ctpy.crs.Robinson()
    sel = ds.loc[{'duration': duration}]
    # reshape variables as dimension
    da_list = []
    for var_name in var_names:
        if sqr == True:
            da_sel = np.square(sel[var_name]).expand_dims('param')
        else:
            da_sel = sel[var_name].expand_dims('param')
        da_sel.coords['param'] = [var_name]
        da_list.append(da_sel)
    da = xr.concat(da_list, 'param')
    da.attrs['long_name'] = value_name  # Color bar title
    # Actual plot
    p = da.plot(col='param', col_wrap=1,
                transform=ctpy.crs.PlateCarree(),
                aspect=ds.dims['longitude'] / ds.dims['latitude'],
                cmap='viridis', robust=True, extend='both',
                subplot_kws=dict(projection=crs)
                )
    for ax, disp_name in zip(p.axes.flat, disp_names):
        ax.coastlines(linewidth=.5, color='black')
        ax.set_title(disp_name)
    # plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def get_site_list(ds, name_col, use_only=None):
    """return a dict {name: (lat, lon)}
    """
    # Set station coordinates to station name
    ds.coords['station'] = ds[name_col]

    if not use_only:
        use_only = ds[name_col].values

    sites = {}
    for name, lat, lon in zip(ds[name_col].values,
                              ds['latitude'].values,
                              ds['longitude'].values):
        if name in use_only:
            sites[name] = (lat, lon)
    return sites


def combine_ds_per_site(site_list, ds_cont=None, ds_points=None):
    """
    """
    if not ds_cont and not ds_cont:
        raise ValueError('No Dataset provided')

    scaling_coeffs = ['location_line_slope', 'scale_line_slope',
                      'location_line_intercept', 'scale_line_intercept',
                      'scaling_ratio']
    keep_vars = ['location', 'scale'] + scaling_coeffs
    drop_coords = [#'latitude', 'longitude',
                   'gumbel_fit']

    # Extract sites values from the datasets. combine all ds along a new 'source' dimension
    ds_site_list = []
    for site_name, site_coord in list(site_list.items()):
        print(site_name)
        ds_site_sources = []
        # Select site on continous ds
        if ds_cont:
            for ds_name, ds in ds_cont.items():
                ds_cont_extract = (ds.sel(latitude=site_coord[0],
                                          longitude=site_coord[1],
                                          method='nearest')
                                    .drop(drop_coords)
                                    [keep_vars])
                ds_cont_extract = ds_cont_extract.load().expand_dims(['station','source'])
                ds_cont_extract.coords['station'] = [site_name]
                ds_cont_extract.coords['source'] = [ds_name]
                ds_site_sources.append(ds_cont_extract)
        # Add point ds
        if ds_points:
            for ds_name, (ds, name_col) in ds_points.items():
                ds.coords['station'] = ds[name_col]
                ds_pt_extract = (ds.sel(station=site_name)
                                 .load()
                                 .drop(drop_coords + [name_col])
                                 [keep_vars])
                ds_pt_extract.coords['station'] = [site_name]
                ds_pt_extract.coords['source'] = [ds_name]
                ds_site_sources.append(ds_pt_extract)
        # Concatenate all sites along the source dimension
        ds_all_sources = xr.concat(ds_site_sources, dim='source')
        ds_site_list.append(ds_all_sources)

    # Concat all along the 'station' dimension
    ds_all = xr.concat(ds_site_list, dim='station')
    # Calculate regression lines
    for p in ['location', 'scale']:
        # ref_D = 6
        # ref_param = ds_all[p].sel(duration=ref_D)
        dur = ds_all['duration']
        slope = ds_all['{}_line_slope'.format(p)]
        intercept = ds_all['{}_line_intercept'.format(p)]
        linereg_var = '{}_lr'.format(p)
        ds_all[linereg_var] = (10**intercept) * dur**slope
    print(ds_all.sel(duration=2, station='Jakarta',
                     scaling_extent=b'daily'))
    return ds_all


def ds_to_df(ds):
    # Create a dict of Pandas DF {'site': DF} with the df col prefixed with the source
    dict_df = {}
    for station in ds['station'].values:
        df_list = []
        for source in ds['source'].values:
            # get scale and location
            ds_extract = ds.sel(station=station,
                                source=source,
                                scaling_extent=ds['scaling_extent'].values[0])
            df = ds_extract.to_dataframe()
            drop_list = ['station', 'source', 'scaling_extent',
                        'location_line_slope', 'scale_line_slope',
                        'scaling_ratio', 'location_lr', 'scale_lr']
            df.drop(drop_list, axis=1, inplace=True)
            rename_rules = {'location': '{}_location'.format(source),
                            'scale': '{}_scale'.format(source)}
            df.rename(columns=rename_rules, inplace=True)
            df_list.append(df)
            # Get regression lines
            for scaling_extent in ds['scaling_extent'].values:
                extent = scaling_extent.decode("utf-8")
                ds_extract2 = ds.sel(station=station,
                                         source=source,
                                         scaling_extent=scaling_extent)
                df2 = ds_extract2.to_dataframe()
                drop_list = ['station', 'source', 'scaling_extent',
                            'location_line_slope', 'scale_line_slope',
                            'scaling_ratio', 'location', 'scale']
                df2.drop(drop_list, axis=1, inplace=True)
                rename_rules = {
                    'location_lr': '{}_location_lr_{}'.format(source, extent),
                    'scale_lr': '{}_scale_lr_{}'.format(source, extent)
                    }
                df2.rename(columns=rename_rules, inplace=True)
                df_list.append(df2)
            # print(df)
        df_all = pd.concat(df_list, axis=1, sort=False)
        dict_df[station] =  df_all
    return dict_df


def plot_point_map(ds, ax):
    ds_sel = ds.sel(duration=ds.duration.values[0],
                    scaling_extent=ds.scaling_extent.values[0],
                    source=ds.source.values[0],)
    df = ds_sel.to_dataframe()
    df['geometry'] = [shapely.geometry.Point(lon, lat)
                      for lon, lat in zip(df['longitude'],
                                          df['latitude'])]
    gdf = gpd.GeoDataFrame(df, geometry='geometry')
    ax.set_global()
    ax.coastlines(linewidth=.3, color='0.6', zorder=0)
    gdf.plot(ax=ax, markersize=25, transform=ctpy.crs.PlateCarree(), zorder=20)
    ax.set_title('Sample sites location')


def plot_scaling_per_site(ds, fig_name):
    """
    """
    linesyles = {
        # 'MIDAS_location': dict(linestyle='None', linewidth=0, marker='v', markersize=3,
        #                        color=C_PRIMARY_1, label='Location $\mu$ (MIDAS)'),
        # 'MIDAS_location_lr': dict(linestyle='solid', linewidth=0.5, marker=None, markersize=0,
        #                           color=C_PRIMARY_1, label='$a d^\\alpha$ (MIDAS)'),
        # 'MIDAS_scale': dict(linestyle='None', linewidth=0, marker='v', markersize=3,
        #                     color=C_PRIMARY_2, label='Scale $\sigma$ (MIDAS)'),
        # 'MIDAS_scale_lr': dict(linestyle='solid', linewidth=0.5, marker=None, markersize=0,
        #                        color=C_PRIMARY_2, label='$\sigma_D (d/D)^\\beta$ (MIDAS)'),
        'ERA5_location': dict(linestyle='None', linewidth=0, marker='o', markersize=2,
                              color=C_SECONDARY_1, label='Location $\mu$'),
        'ERA5_scale': dict(linestyle='None', linewidth=0, marker='o', markersize=2,
                           color=C_SECONDARY_2, label='Scale $\sigma$'),
        'ERA5_location_lr_all': dict(linestyle='solid', linewidth=1., marker=None, markersize=0,
                                 color=C_SECONDARY_1, label='$a d^\\alpha$ (all)'),
        'ERA5_scale_lr_all': dict(linestyle='solid', linewidth=1., marker=None, markersize=0,
                              color=C_SECONDARY_2, label='$b d^\\beta$ (all)'),
        'ERA5_location_lr_daily': dict(linestyle='dashed', linewidth=1., marker=None, markersize=0,
                                 color=C_SECONDARY_1, label='$a d^\\alpha$ (daily)'),
        'ERA5_scale_lr_daily': dict(linestyle='dashed', linewidth=1., marker=None, markersize=0,
                              color=C_SECONDARY_2, label='$b d^\\beta$ (daily)'),
                }

    dict_df = ds_to_df(ds)
    col_num = 2
    row_num = math.ceil(len(dict_df) / col_num)
    fig_size = (3.5*col_num, 2*row_num)
    fig = plt.figure(figsize=fig_size)
    ax_num = 1

    # Draw map
    ax_map = fig.add_subplot(row_num, col_num, ax_num,
                             projection=ctpy.crs.Robinson(),
                             aspect='auto')
    plot_point_map(ds, ax_map)
    ax_num += 1

    sites_ax_list = []
    for site_ax_num, (site_name, df) in enumerate(dict_df.items()):
        if site_ax_num == 0:
            ax = fig.add_subplot(row_num, col_num, ax_num)
            first_ax = ax
        else:
            ax = fig.add_subplot(row_num, col_num, ax_num,
                                 sharex=first_ax, sharey=first_ax)
        print(site_name)
        # plot
        for col, styles in linesyles.items():
            try:
                df[col].plot(ax=ax, label=styles['label'],
                        # title=site_name.decode("utf-8"),
                        title=site_name,
                        loglog=True,
                        # logx=True,
                        linestyle=styles['linestyle'], linewidth=styles['linewidth'],
                        markersize=styles['markersize'],
                        marker=styles['marker'], color=styles['color'])
            except KeyError:
                continue
        lines, labels = ax.get_legend_handles_labels()
        ax.set_xlabel('$d$ (hours)')
        ax.set_ylabel('$\mu, \sigma$')
        sites_ax_list.append(ax)
        # Text box
        # table_row = "{:<11s} {:>5.2f} {:>8.2f} {:>5.2f}\n"
        # txt = ["{:<11s} {:>5s} {:>8s} {:>5s}\n".format('Parameter', 'ERA5', 'ERA5 day', 'GHCN'),
        #        table_row.format('Loc. slope',
        #                         #'$\eta(\mu)$',
        #                         df_scaling_coeffs.loc['loc_lr_slope', 'ERA5'],
        #                         df_scaling_coeffs.loc['loc_lr_slope', 'ERA5_MULTIDAILY'],
        #                         df_scaling_coeffs.loc['loc_lr_slope', 'GHCN']),
        #        table_row.format('Scale slope',
        #                         #'$\eta(\sigma)$',
        #                         df_scaling_coeffs.loc['scale_lr_slope', 'ERA5'],
        #                         df_scaling_coeffs.loc['scale_lr_slope', 'ERA5_MULTIDAILY'],
        #                         df_scaling_coeffs.loc['scale_lr_slope', 'GHCN']),
        #        table_row.format('Slope ratio',
        #                         #'$\eta(\mu) / \eta(\sigma)$',
        #                         df_scaling_coeffs.loc['scaling_ratio', 'ERA5'],
        #                         df_scaling_coeffs.loc['scaling_ratio', 'ERA5_MULTIDAILY'],
        #                         df_scaling_coeffs.loc['scaling_ratio', 'GHCN'])
        #     ]
        # t = ax.text(0.01, 0.0, ''.join(txt), backgroundcolor='white',
        #             horizontalalignment='left', verticalalignment='bottom',
        #             transform=ax.transAxes, size=7, family='monospace'
        #             )
        # t.set_bbox(dict(alpha=0))  # force transparent background
        ax_num += 1

    # set ticks
    for ax in sites_ax_list:
        ax.set_xticks(XTICKS)
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())

    # plt.legend(lines, labels, loc='lower center', ncol=4)

    lgd = fig.legend(lines, labels, loc='lower center', ncol=3)
    plt.tight_layout()
    plt.subplots_adjust(bottom=.12, wspace=None, hspace=None)
    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def plot_hourly(ds, sites, fig_name):
    ds_list = []
    for site_name, site_coord in sites.items():
        ds_list.append(ds.sel(latitude=site_coord[0],
                       longitude=site_coord[1],
                       method='nearest'))
    drop_coords = ['latitude', 'longitude']
    ds_sites = xr.concat(ds_list, dim='site').drop(drop_coords)
    ds_sites.coords['site'] = list(sites.keys())
    p = ds_sites['precipitation'].plot(col='site')
    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def plot_gumbel_per_site(ds, sites, fig_name):
    DURATION = 6
    # extract sites values from the dataset as pandas dataframes
    dict_cdf = {}
    for site_name, site_coord in sites.items():
        dict_pvalues = {}
        ds_sel = ds.sel(latitude=site_coord[0],
                        longitude=site_coord[1],
                        duration=DURATION,
                        method='nearest').drop(['latitude', 'longitude', 'duration'])
        # Keep only wanted values as dataframe
        keep_col = ['estim_prob', 'analytic_prob_moments', 'analytic_prob_loaiciga', 'annual_max']
        df_cdf = ds_sel[keep_col].load().to_dataframe().set_index('annual_max', drop=True).sort_index()
        dict_cdf[site_name] = df_cdf

    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(8,4))
    for (site_name, df), ax in zip(dict_cdf.items(), axes):
        dict_cdf[site_name].plot(linestyle=None, marker='o', markersize=1.5,
                                 title=site_name, ax=ax, legend=False)
        lines, labels = ax.get_legend_handles_labels()
        ax.set_ylabel('Cumulative probability')
        txt = "Dcrit = {:.2f}".format(ds['Dcrit_5pct'].values)
        ax.text(0.65, 0.10, txt, horizontalalignment='left', backgroundcolor='white',
                verticalalignment='center', transform=ax.transAxes, size=10)
    fig.suptitle('Cumulative probability for a duration of {} hours'.format(DURATION))
    lgd_labels = ['Estimated CDF',
                  'Analytic CDF (method of moments)',
                  'Analytic CDF (iterative method)']
    lgd = fig.legend(lines, lgd_labels, loc='lower center', ncol=4)
    # plt.tight_layout()
    plt.subplots_adjust(bottom=.24, wspace=None, hspace=None)
    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def plot_gauges_data(ds, ymin, ymax, fig_name):
    """Plot the completeness of the gauges data
    """
    da_year_count = ds['precipitation'].groupby('date.year').count(dim='date')
    year_count_sel = da_year_count.sel(year=slice(ymin, ymax))
    # plot
    p = year_count_sel.plot(vmin=int(365*.9))
    ax = plt.gca()
    labels = list(da_year_count['code'].values)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def plot_gauges_map(ds, id_dim, fig_name, global_extent=True):
    """convert dataset in geopandas DataFrame
    plot it
    """
    # Create a GeoDataFrame
    ds_sel = ds.sel(duration=24, year=2000)#['annual_max']
    df = ds_sel.to_dataframe().set_index(id_dim, drop=True).drop(axis=1, labels=['annual_max', 'year', 'duration'])
    df['geometry'] = [shapely.geometry.Point(lon, lat) for lon, lat in zip(df['longitude'], df['latitude'])]
    gdf = gpd.GeoDataFrame(
        df, geometry='geometry')#.cx[slice(-2, -1.5), slice(51, 52)]
    print(gdf)

    # Plot the gauges on a world map
    plt.figure(figsize=(12, 12))
    if global_extent:
        ax_p = plt.gca(projection=ctpy.crs.Robinson(), aspect='auto')
        ax_p.set_global()
    else:
        ax_p = plt.gca(projection=ctpy.crs.PlateCarree(), aspect='auto')
        gl = ax_p.gridlines(crs=ctpy.crs.PlateCarree(), linewidth=.3,
                            #color='black', alpha=0.5, linestyle='--',
                            draw_labels=False,
                            xlocs=np.arange(-10,10,0.25),
                            ylocs=np.arange(45,70,0.25),
                            )
    ax_p.coastlines(linewidth=.3, color='black')
    gdf.plot(ax=ax_p, markersize=5, transform=ctpy.crs.PlateCarree())


    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def hexbin(ds, var1, var2, xlabel, ylabel, fig_name):
    x = ds[var1].values.flat
    y = ds[var2].values.flat
    xq = np.nanquantile(x, [0.01, 0.99])
    yq = np.nanquantile(y, [0.01, 0.99])
    xmin, xmax = xq[0], xq[1]
    ymin, ymax = xq[0], xq[1]

    fig, ax = plt.subplots(figsize=(4, 3))
    # ax.axis([xmin, xmax, ymin, ymax])
    hb = ax.hexbin(x, y, gridsize=20, extent=[xmin, xmax, ymin, ymax],
                   mincnt=1, bins=None)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.plot([xmin, xmax], [ymin, ymax], color='k', linewidth=0.5)
    norm = matplotlib.colors.Normalize(vmin=1000, vmax=12000)
    cb = plt.colorbar(hb, spacing='uniform', orientation='vertical',
                      label='Number of cells', norm=norm, extend='both')
    # cb.set_label('# of cells')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOT_DIR, fig_name))
    plt.close()


def fig_map_anderson(ds):
    """create a map of the Anderson-Darling A^2 for Gumbel
    """
    # print(ds)
    a2_mean = ds['A2'].mean(dim='duration')
    a2_crit = ds['A2_crit'].sel(significance_level=1).values
    print(ds['A2'].where(ds['A2'] > a2_crit).count(dim=['latitude', 'longitude']).mean().compute())
    single_map(a2_mean,
               title='',
               cbar_label='$A^2$',
               center=a2_crit,
               reverse=True,
               fig_name='A2_2000-2017_1pct.png')


def table_anderson_quantiles(ds, dim):
    # print(ds['scaling_extent'].load())
    q = ds['A2'].load().quantile([0.01, 0.5, 0.95, 0.99], dim=dim)
    # print(q)
    a2_mean = ds['A2'].mean(dim='duration')
    print(a2_mean)
    sig = ds['A2_crit'].sel(significance_level=5)
    print(sig)
    print(a2_mean.where(a2_mean <= sig, drop=True))
    # print(ds['A2_crit'])


def fig_maps_gumbel24h(ds):
        multi_maps(ds, ['location', 'scale'],
                ['Location $\mu$', 'Scale $\sigma$'],
                'Parameter value', 'gumbel_params_24h_2000-2017.png')


def fig_maps_gumbel1h(ds):
        multi_maps(ds, ['location', 'scale'],
                   ['Location $\mu$', 'Scale $\sigma$'],
                   'Parameter value', 'gumbel_params_1h_2000-2017.png',
                   duration=1)


def table_rsquared_quantiles(ds, dim):
    # print(ds['scaling_extent'].load())
    ds_rsquared = ds[['location_line_rvalue', 'scale_line_rvalue']].sel(scaling_extent=['daily', 'all'])**2
    q =  ds_rsquared.load().quantile([0.01, 0.5, 0.99], dim=dim)
    print(q['location_line_rvalue'])
    print(q['scale_line_rvalue'])


def table_r_quantiles(ds, dim):
    # print(ds['scaling_extent'].load())
    ds_r = ds[['location_line_rvalue', 'scale_line_rvalue']].sel(scaling_extent=[b'daily', b'all'])
    q = ds_r.load().quantile([0.01, 0.5, 0.99, 0.999], dim=dim)
    print(q['location_line_rvalue'])
    print(q['scale_line_rvalue'])


def table_r_sigcount(ds, alpha, dim):
    ds_r = ds[['location_line_pvalue', 'scale_line_pvalue']].sel(scaling_extent=[
                                                                 b'daily', b'all'])
    print(ds_r.where(ds_r > alpha).count(dim=dim).load())


def fig_maps_r(ds):
    multi_maps(ds.sel(scaling_extent=b'daily'), ['location_line_rvalue', 'scale_line_rvalue'],
               ['Location', 'Scale'],
               '$r$', 'gumbel_r_daily.png', sqr=False)


def fig_maps_rsquared(ds):
    multi_maps(ds.sel(scaling_extent=b'daily'), ['location_line_rvalue', 'scale_line_rvalue'],
               ['Location', 'Scale'],
               '$r^2$', 'gumbel_r2_daily.png', sqr=False)


def get_quantile_dict(quantiles, **kwargs):
    """
    kwargs: a dict of 'source': (ds, dim)
    return df_dict: {param: [(source, df), ]}
    """
    df_dict = {}
    for param in ['location', 'scale']:
        # Actual values of the regression lines
        df_list = []
        for source, (ds, dim) in kwargs.items():
            try:
                ds_daily = ds.sel(scaling_extent=b'daily')
            except KeyError:
                ds_daily = ds.sel(scaling_extent='daily')
            slope = ds_daily['{}_line_slope'.format(param)]
            intercept = ds_daily['{}_line_intercept'.format(param)]
            log_reg = np.log10(10**intercept * ds_daily['duration']**slope)
            diff = log_reg - ds_daily['log_{}'.format(param)]
            diff_q = diff.compute().quantile(quantiles, dim=dim)
            df_q = diff_q.to_dataset('quantile').to_dataframe()
            df_list.append((source, df_q))
        df_dict[param] = df_list
    return df_dict


def fig_scaling_differences_all(ds_era, ds_midas):
    quantiles = [0.01, 0.5, 0.99]

    ds_era_sel = ds_era.sel(latitude=ds_midas['latitude'],
                            longitude=ds_midas['longitude'],
                            method='nearest')

    q_extent_dict = {
        'Whole world': get_quantile_dict(quantiles,
                                         ERA5=(ds_era, ['latitude', 'longitude']),
                                         ),
        'MIDAS stations': get_quantile_dict(quantiles,
                                            ERA5=(ds_era_sel, ['station']),
                                            MIDAS=(ds_midas, ['station'])
                                            ),
        }

    # Flatten the dict
    q_list = []
    for extent, df_dict in q_extent_dict.items():
        for param, df_list in df_dict.items():
            q_list.append({'extent':extent,
                           'param':param,
                           'df_list':df_list})

    fig_name = 'scaling_diff.pdf'
    col_num = len(q_extent_dict)
    row_num = 2
    fig, axes = plt.subplots(row_num, col_num, figsize=(6, 3),
                             sharey='row', sharex=True)

    # param in rows, extent in columns
    for row_num, (param, ax_row) in enumerate(zip(['location', 'scale'], axes)):
        for extent, ax in zip(q_extent_dict, ax_row):
            df_list = [i['df_list'] for i in q_list
                        if i['extent'] == extent
                        and i['param'] == param][0]
            plot_scaling_differences(param, df_list, ax)
            if row_num == 0:
                ax.set_title(extent)

    # set ticks
    for ax in axes.flat:
        ax.set_xticks(XTICKS)
        ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())

    # add a big axes, hide frame
    # fig.add_subplot(111, frameon=False)
    # # hide tick and tick label of the big axes
    # plt.tick_params(labelcolor='none', top=False,
    #                 bottom=False, left=False, right=False)
    # plt.grid(False)
    # ylabel = '$\log_{{10}}( d^{{\eta}} / (\mu, \sigma) )$'
    # plt.ylabel(ylabel)

    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=2)
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.35, left=0.15, wspace=None, hspace=None)
    plt.savefig(os.path.join(PLOT_DIR, fig_name), bbox='tight')
    plt.close()


def plot_scaling_differences(param, df_list, ax):
    """
    Plot quantiles of differences
    """
    ylim = {'location': [-0.25, 0.75], 'scale': [-0.6, 1.1]}
    param_symbols = {'location': '\mu_d', 'scale': '\sigma_d'}
    gradient_symbols = {'location': '\\alpha', 'scale': '\\beta'}
    intercept_symbols = {'location': 'a', 'scale': 'b'}

    for (source, df), color in zip(df_list, [C_PRIMARY_1, C_PRIMARY_2]):
        quantiles = df.columns.values
        q_min = quantiles[0]
        q_max = quantiles[-1]
        title = '{} ${}$'.format(param.title(), param_symbols[param])
        fill_label = '{} Q{} to Q{}'.format(source, int(q_min*100), int(q_max*100))
        df[0.5].plot(logx=True, logy=False, ax=ax,
                        linewidth=1, color=color, zorder=10,
                    #  title=title,
                        label='{} median'.format(source))
        ax.fill_between(df.index, df[q_min], df[q_max],
                        facecolor=color, alpha=0.2, zorder=1,
                        label=fill_label)
    ax.axhline(0, linewidth=0.1, color='0.5')
    ax.axvline(24, linewidth=0.1, color='0.5')
    ax.set_ylim(ylim[param])
    # ax.set_yticks([ 0.0, 0.5])
    ax.set_xticks(XTICKS)
    ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
    ax.set_xlabel('$d$ (hours)')
    ylabel = '$\log_{{10}}( {i}d^{g} / {p} )$'.format(g=gradient_symbols[param],
                                                        p=param_symbols[param],
                                                        i=intercept_symbols[param])
    ax.set_ylabel(ylabel)



def fig_scaling_ratio_map(ds):
    scaling_ratio = ds['scaling_ratio'].sel(scaling_extent=b'all')
    # print(scaling_ratio)
    new_lat = scaling_ratio['latitude'].values[::1]
    new_long = scaling_ratio['longitude'].values[::1]
    # print(new_long)
    resamp = scaling_ratio.dropna('latitude').dropna('longitude').load().interp(latitude=new_lat, longitude=new_long)
    # print(resamp)
    single_map(resamp,
               title="",
               cbar_label='$\\alpha / \\beta$',
               center=1.0,
               fig_name='scaling_ratio2000-2017.png')


def fig_scaling_gradients_maps(ds):
    multi_maps(ds.sel(scaling_extent=b'daily'), ['location_line_slope', 'scale_line_slope'],
               ['Location-duration scaling', 'Scale-duration scaling'],
               "$\\alpha, \\beta$", 'scaling_gradients_2000-2017_superdaily.png', sqr=False)


def fig_scaling_hexbin(ds):
    hexbin(ds.sel(scaling_extent=b'all'),
           'location_line_slope', 'scale_line_slope',
           '$\\alpha$', '$\\beta$',
           'scaling_gradients_hexbin.png')


def table_count_nogumbelfit(ds):
    num_null = (~np.isfinite(ds['location'])).sum(dim=['latitude', 'longitude'])
    print(num_null.load())


def table_count_noscalingfit(ds):
    num_null = np.isnan(ds[['location_line_slope', 'scale_line_slope']]).sum(dim=['latitude', 'longitude'])
    print(num_null.load())


def station_permut(ds):
    stations = ds['station'].values
    combinations = list(itertools.combinations(stations, 2))
    print(combinations[:100])
    print(len(combinations))


def main():
    ds_era = xr.open_zarr(os.path.join(DATA_DIR, ERA_ANNUAL_FILE)).sel(gumbel_fit=b'scipy')
    ds_midas = xr.open_dataset(MIDAS_ANNUAL_FILE).sel(gumbel_fit='scipy')
    # print(ds_era)
    # print(ds_midas)
    # station_permut(ds_midas)


    # fig_map_anderson(ds_era)
    # table_anderson_quantiles(ds_midas, dim=None)
    # fig_maps_gumbel24h(ds_era)
    # fig_maps_gumbel1h(ds_era)
    # table_count_nogumbelfit(ds_era)
    # table_count_noscalingfit(ds_era)
    # table_r_quantiles(ds_era, dim=['longitude', 'latitude'])
    # table_r_sigcount(ds_era, 0.05, dim=['longitude', 'latitude'])
    # table_r_sigcount(ds_era, 0.01, dim=['longitude', 'latitude'])
    # fig_scaling_gradients_maps(ds_era)
    # fig_scaling_differences_all(ds_era, ds_midas)
    # fig_maps_r(ds_era)
    # fig_scaling_ratio_map(ds_era)
    # fig_scaling_hexbin(ds_era)

    # fig_map_anderson(ds_era)
    # ds_ghcn = xr.open_dataset(GHCN_ANNUAL_FILE)
    # print(ds_ghcn)
    # print(ds_ghcn)
    # print(ds_annual_midas)
    # print(ds_annual_midas['location_line_rvalue'].load())
    # print(ds_annual_midas['A2'].load())
    # print(ds_annual_midas['A2'].load().quantile([0.50, 0.8, 0.9, 0.95,0.99,0.999]))



    # ds_annual_ghcn = xr.open_zarr(GAUGES_ANNUAL_FILE)
    # print(ds_annual_gauges.load())
    # print(ds_annual_midas.load())
    # plot_gauges_map(ds_annual_midas, 'src_name', 'midas_gauges_map.pdf', global_extent=False)
    # plot_gauges_map(ds_ghcn, 'name', 'ghcn_gauges_map.pdf', global_extent=True)
    # plot_gauges_data(ds_ghcn, 2000, 2012 'gauges.png')

    # print((~np.isfinite(ds)).sum().compute())
    # plot_gumbel_per_site(ds_era, STUDY_SITES, 'sites_gumbel.png')
    # use_stations = [b'BRIZE NORTON', b'LITTLE RISSINGTON',
    #                 b'LARKHILL', b'BOSCOMBE DOWN']
    # ds_points = {'MIDAS': (ds_midas.sel(scaling_extent='daily'), 'src_name')}
    # sites_list = get_site_list(ds_midas, 'src_name', use_only=use_stations)
    # dict_df = prepare_scaling_per_site(sites_list,
    #                                    ds_cont=ds_cont,
    #                                    ds_points=ds_points
    #                                    )
    # plot_scaling_per_site(dict_df, 'sites_scaling_midas_select_2000-2017_test.pdf')

    ds_cont = {'ERA5': ds_era.sel(scaling_extent=[b'daily', b'all'])}
    ds = combine_ds_per_site(STUDY_SITES, ds_cont=ds_cont, )
    plot_scaling_per_site(ds, 'sites_scaling_select_2000-2017.pdf')



    # single_map(ds_era['scaling_pearsonr'],
    #            title="$d^{\eta(\mu)}$ - $d^{\eta(\sigma)}$ correlation",
    #            cbar_label='Pearson correlation coefficient',
    #            fig_name='pearsonr.png')

    # single_map(ds_era['scaling_spearmanr'],
    #        title="Parameter scaling correlation",
    #        cbar_label="Spearman's $\\rho$",
    #        fig_name='spearmanr.png')

    # multi_maps(ds_era, ['ks_loaiciga', 'ks_moments'],
    #            ['Fitting accuracy of the iterative method (d=24h)', 'Fitting accuracy of the method of moments (d=24h)'],
    #            "Kolmogorov-Smirnov's D", 'fitting_accuracy.png', sqr=False)

    # hourly_path = os.path.join(DATA_DIR, HOURLY_FILE)
    # hourly = xr.open_zarr(hourly_path)
    # plot_hourly(hourly, STUDY_SITES, 'hourly.png')

    # hourly maxima
    # hourly_max = hourly['precipitation'].max('time')
    # print(hourly_max)
    # single_map(hourly_max,
    #            title="Max hourly precipitation 2000-2012 (ERA5)",
    #            cbar_label='Precipitation rate (mm/hr)',
    #            fig_name='hourly_max.png')

    # ds_midas = xr.open_zarr('/home/lunet/gylc4/geodata/MIDAS/midas_precip_1950-2017.zarr')
    # ds_midas.coords['station'] = ds_midas['src_name']
    # print(ds_midas)
    # da_larkhill = ds_midas['ob_hour_count'].sel(station='LARKHILL', end_time=slice(str(2000), str(2017)))
    # da_larkhill.plot()
    # plt.savefig('larkhill.pdf')
    # plt.close()
    # block_one = ['BRIZE NORTON', 'LITTLE RISSINGTON']
    # block_two = ['LARKHILL', 'BOSCOMBE DOWN']

if __name__ == "__main__":
    sys.exit(main())

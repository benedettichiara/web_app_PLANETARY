import streamlit as st
import xarray as xr
import numpy as np
import pandas as pd
import os
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
import tempfile
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pystac_client
import planetary_computer
import geopandas as gpd
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import rioxarray


def calculate_djf_sum(data_array):
    # Create a new 'year' coordinate for grouping, shifting December to the next year
    year_shifted = data_array.time.dt.year + (data_array.time.dt.month == 12)

    # Assign this 'year' coordinate to the DataArray
    data_array = data_array.assign_coords(djf_year=year_shifted)

    # Select DJF months (Dec of the previous year from the original, Jan and Feb of the current 'djf_year')
    djf_data = data_array.where(data_array.time.dt.month.isin([1, 2, 12]), drop=True)

    # Now, group by this 'djf_year' and sum to get DJF precipitation sum
    djf_sum = djf_data.groupby('djf_year').sum(dim="time")

    return djf_sum



def round_coordinates(coord, interval=0.25):
    """Rounds the coordinates to the nearest grid point."""
    return [round(c / interval) * interval for c in coord]

def fetch_rain_bbox(varname, factor, location, start_date, end_date):
    """
    Fetches ERA5 precipitation data for a specified bounding box, date range, and variable name,
    accumulating the data monthly.
    """
    catalog = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1/")
    monthly_dataarrays = []

    current_month_start = pd.to_datetime(start_date)
    while current_month_start <= pd.to_datetime(end_date):
        next_month_start = (current_month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        current_month_end = next_month_start - timedelta(days=1)

        search_results = catalog.search(
            collections=["era5-pds"], datetime=[current_month_start.isoformat(), current_month_end.isoformat()], query={"era5:kind": {"eq": "fc"}}
        )

        items = list(search_results.items())
        for item in items:
            signed_item = planetary_computer.sign(item)
            asset = signed_item.assets.get(varname)
            if asset:
                dataset = xr.open_dataset(asset.href, **asset.extra_fields["xarray:open_kwargs"])
                wind_ds = dataset[varname]
                interval = 0.25
                rounded_coord = round_coordinates(location, interval)
                wind_ds_sliced = wind_ds.sel(lat=slice(rounded_coord[1], rounded_coord[0]), lon=slice(rounded_coord[2], rounded_coord[3])) * factor
                monthly_dataarrays.append(wind_ds_sliced)
        
        current_month_start = next_month_start

    # Concatenate all monthly DataArrays along the time dimension if any data was fetched
    if monthly_dataarrays:
        combined = xr.concat(monthly_dataarrays, dim="time")
        return combined
    else:
        return None

def convert_to_netcdf(data_era5):
    # Create a temporary directory to save the file
    if not os.path.exists('tmp'):
        os.makedirs('tmp')
    filepath = os.path.join('tmp', 'era5_data.nc')
    data_era5.to_netcdf(path=filepath)
    return filepath
from datetime import datetime

def fetch_and_map_sentinel2(location, start_date, end_date):
    """
    Fetches the most recent Sentinel-2 image from Planetary Computer for a specified bounding box
    and date range, and maps it with state boundaries.
    
    Parameters:
    - location: tuple of (min_lon, min_lat, max_lon, max_lat)
    - start_date: start date for the search
    - end_date: end date for the search
    """
    catalog = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1/")
    
    # Perform the search for Sentinel-2 data
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=location,
        datetime=f"{start_date}/{end_date}",
        limit=1,
        query={"eo:cloud_cover": {"lt": 10}}  # Optional: Filter by cloud cover
    )


    
    # Get the first matching item
    items = list(search.get_items())
    if not items:
        st.error("No Sentinel-2 data found for the specified parameters.")
        return
    
    item = items[0]
    signed_item = planetary_computer.sign(item)  # Sign the item to access the data

    # Load the image
    data_asset = signed_item.assets["visual"]
    visual_data = rioxarray.open_rasterio(data_asset.href)
    
    # Plotting the image
    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw={'projection': ccrs.PlateCarree()})
    
    # Select the first band for visualization (RGB combination)
    img_extent = [location[0], location[2], location[1], location[3]]
    ax.imshow(visual_data[0].data, extent=img_extent, transform=ccrs.PlateCarree(), origin='upper')
    
    # Add state boundaries and coastlines
    ax.add_feature(cfeature.STATES, edgecolor='black')
    ax.coastlines()

    # Set labels and title
    ax.set_title(f"Sentinel-2 Image for Bounding Box: {location}\nDate: {signed_item.datetime.isoformat()}", fontsize=12)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    
    # Display using Streamlit
    st.pyplot(fig)

def main():
    # Streamlit interface for inputs
    st.title("ERA5  Data Download")
    start_date = st.date_input("Start date", value=datetime(1995, 1, 1))
    end_date = st.date_input("End date", value=datetime(1995, 12, 31))
    
    lat_min = st.number_input("Latitude Min:", value=-31.0)
    lat_max = st.number_input("Latitude Max:", value=-29.0)
    lon_min = st.number_input("Longitude Min:", value=26.0)
    lon_max = st.number_input("Longitude Max:", value=29.0)
    location = [lat_min, lat_max, lon_min, lon_max]
    location1 = [lon_min, lat_min, lon_max, lat_max]
    location_str = ', '.join(map(str, location1))
    print(location_str)

    #var_ERA5 = st.selectbox( "ERA5variable", ('precipitation_amount_1hour_Accumulation', 'air_temperature_at_2_metres_1hour_Maximum', 'air_temperature_at_2_metres_1hour_Minimum','eastward_wind_at_10_metres','northward_wind_at_10_metres'),
    #                        index=None,placeholder="Select Variable.",)

    var_ERA5 = st.selectbox(
    label="Select an ERA5 Variable",
    options=[
        'precipitation_amount_1hour_Accumulation', 
        'air_temperature_at_2_metres_1hour_Maximum', 
        'air_temperature_at_2_metres_1hour_Minimum',
        'eastward_wind_at_10_metres', 
        'northward_wind_at_10_metres'
    ],
    index=0,  # Default selection to the first variable
    help="Choose the variable you wish to analyze from ERA5 data.")
    st.write(f"Selected variable: {var_ERA5}")
    
    #st.write('You selected:', var_ERA5)
    if var_ERA5=='precipitation_amount_1hour_Accumulation':
        factor_sel=1000
    else:
        factor_sel=1

    varname_Rain = "precipitation_amount_1hour_Accumulation"
    factor = 1000  # Adjust the factor as necessary

    
    # Button to fetch and process the data
    if st.button("Fetch ERA5 Precipitation Data"):
        precipitation_data = fetch_rain_bbox(varname_Rain, factor, location, start_date, end_date)
        precipitation_data = precipitation_data.rename('precipitation')
        daily_precipitation = precipitation_data.resample(time='D').sum()
        historical_djf_sum = calculate_djf_sum(daily_precipitation)
        historical_djf_sum = historical_djf_sum.chunk({'djf_year': -1})
        lower_tercile = historical_djf_sum.quantile(0.33, dim="djf_year")
        upper_tercile = historical_djf_sum.quantile(0.67, dim="djf_year")
         # Plotting lower tercilet with custom color scale
        fig = px.imshow(lower_tercile, 
                        labels=dict(x="Longitude", y="Latitude", color="lower_tercile"),
                        x=lower_tercile.lon,
                        y=lower_tercile.lat)
        
        fig.update_traces(hoverinfo='x+y+z', showscale=True)
        st.plotly_chart(fig, use_container_width=True)  


        # Create a figure
        fig, ax = plt.subplots(figsize=(10, 5), subplot_kw={'projection': ccrs.PlateCarree()})
        lon = np.linspace(lon_min, lon_max, lower_tercile.shape[1])  # Replace with actual longitude data
        lat = np.linspace(lat_min, lat_max, lower_tercile.shape[0])     # Replace with actual latitude data

        # Plot data
        c = ax.pcolormesh(lon, lat, lower_tercile, transform=ccrs.PlateCarree(), cmap='viridis')

        # Add state boundaries
        ax.add_feature(cfeature.STATES, edgecolor='black')

        # Add coastlines
        ax.coastlines()

        # Add color bar
        plt.colorbar(c, ax=ax, orientation='vertical', label='lower_tercile')

        # Set labels
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

        # Display using Streamlit
        st.pyplot(fig)

    select_start_date = st.date_input("Select date", value=datetime(2024, 9, 20))
    select_end_date = st.date_input("Select date", value=datetime(2024, 9, 22))
    if st.button('Map Sentinel 2'):
        
        location = (lon_min, lat_min, lon_max, lat_max)  # Example bounding box (min_lon, min_lat, max_lon, max_lat) 
        fetch_and_map_sentinel2(location, select_start_date, select_end_date)



        # Convert to GeoDataFrame (if necessary)
        # Plot with Mapbox overlay
        # Mapbox access token
        
        

if __name__ == "__main__":
    main()

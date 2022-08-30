# Py-Insta-Scraper

*Scrape and download content from Instagram with just an account*

*WARNING*: Before using this library, I highly recommend creating a dummy account and using a VPN to avoid issues with your primary Instagram account.

`py-insta-scraper` can currently asynchronously download the content from every post belonging to a group of users defined in `src/config/config.toml` (see [`sample-config.toml`](https://github.com/hydrobeam/py-insta-scraper/blob/main/src/config/sample_config.toml) for an example config). 

## Installation

This library uses [Selenium](https://selenium-python.readthedocs.io/installation.html) with a Chrome driver to login into Instagram and setup a session from which queries can be made. As such, the driver must be [installed](https://sites.google.com/chromium.org/driver/) beforehand.

Also, [`poetry`](https://python-poetry.org/docs/master/#installing-with-the-official-installer) is used to manage dependencies, so it must be available on your system. To install and run, simply call:

``` bash
poetry install
```

Which will setup a virtual environment and activate it. To reactivate it in future sessions:

``` bash
poetry shell
```

After populating the config file with credentials and users to scrape, from the root of the project, run:

``` bash
python src/core.py
```

to download content to the `output` directory.

## Credits

Thanks to [`instagram-php-scraper`](https://github.com/postaddictme/instagram-php-scraper) for compiling a collection of endpoints. 




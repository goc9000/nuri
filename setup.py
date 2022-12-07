from setuptools import setup, find_packages

setup(
    name='atmfjstc-nuri',
    version='0.3.0',

    author_name='Atom of Justice',
    author_email='atmfjstc@protonmail.com',

    package_dir={'': 'src'},
    packages=find_packages(where='src'),

    entry_points={
        'console_scripts': [
            'nuri = atmfjstc.nuri.__init__:main',
        ]
    },

    zip_safe=True,

    description="Simple configuration/control utility for NGINX Unit",

    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Utilities",
        "Typing :: Typed",
    ],
    python_requires='>=3.7',
)

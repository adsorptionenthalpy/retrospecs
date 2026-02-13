from setuptools import setup, find_packages

setup(
    name="retrospecs",
    version="1.0.0",
    description="CRT shader overlay application",
    packages=find_packages(),
    python_requires=">=3.6",
    install_requires=[
        "PyQt5>=5.12",
        "PyOpenGL>=3.1.5",
        "numpy>=1.19",
        "mss>=6.0",
    ],
    entry_points={
        "console_scripts": [
            "retrospecs=retrospecs.app:main",
        ],
    },
)

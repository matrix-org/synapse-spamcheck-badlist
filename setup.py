from setuptools import find_packages, setup

setup(
    name="synapse-spamcheck-badlist",
    version="0.3.2",
    packages=find_packages(),
    description="A Synapse spam filter designed to block links and upload of content already known as bad. The typical use case is to plug this with a list of links and MD5s of child sexual abuse, as published by the IWF.",
    include_package_data=True,
    zip_safe=True,
    install_requires=["pyahocorasick", "prometheus-client", "twisted", "matrix-synapse"],
    author="David Teller",
    author_email="davidt@element.io",
    license="Apache 2",
)

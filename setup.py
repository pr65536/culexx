from setuptools import setup

setup(name='culexx',
    version='0.1',
    description='MQTT micro library',
    url='http://github.com/tiabas/culexx',
    author='Kevin Mutyaba',
    author_email='tiabasnk@gmail.com'
    packages=['culexx'],
    install_requires=[
      'paho-mqtt',
    ],
    test_suite='nose.collector',
    tests_require=['nose'],
    zip_safe=False)
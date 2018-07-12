Microsoft Azure SDK for Python
==============================

This is the Microsoft Azure Compute Resource Management Client Library.

Azure Resource Manager (ARM) is the next generation of management APIs that
replace the old Azure Service Management (ASM).

This package has been tested with Python 2.7, 3.3, 3.4 and 3.5.

For the older Azure Service Management (ASM) libraries, see
`azure-servicemanagement-legacy <https://pypi.python.org/pypi/azure-servicemanagement-legacy>`__ library.

For a more complete set of Azure libraries, see the `azure <https://pypi.python.org/pypi/azure>`__ bundle package.


Compatibility
=============

**IMPORTANT**: If you have an earlier version of the azure package
(version < 1.0), you should uninstall it before installing this package.

You can check the version using pip:

.. code:: shell

    pip freeze

If you see azure==0.11.0 (or any version below 1.0), uninstall it first:

.. code:: shell

    pip uninstall azure


Usage
=====

For code examples, see `Compute and Network Resource Management 
<https://azure-sdk-for-python.readthedocs.org/en/latest/resourcemanagementcomputenetwork.html>`__
on readthedocs.org.


Provide Feedback
================

If you encounter any bugs or have suggestions, please file an issue in the
`Issues <https://github.com/Azure/azure-sdk-for-python/issues>`__
section of the project.


.. :changelog:

Release History
===============

0.33.0 (2017-02-03)
+++++++++++++++++++

**Features**

This release adds Managed Disk to compute. This changes the default disk creation behavior
to use the new Managed Disk feature instead of Storage.

0.32.1 (2016-11-14)
+++++++++++++++++++

* Add "Kubernetes" on Containers
* Improve technical documentation

0.32.0 (2016-11-02)
+++++++++++++++++++

**Breaking change**

New APIVersion for "container" 2016-09-30.

* several parameters (e.g. "username") now dynamically check before REST calls validity 
  against a regexp. Exception will be TypeError and not CloudError anymore.

0.31.0 (2016-11-01)
+++++++++++++++++++

**Breaking change**

We renamed some "container" methods to follow Azure SDK conventions

* "container" attribute on the client is now "containers"
* "list" changed behavior, now listing containers in subscription and lost its parameter
* "list_by_resource_group" new method with the old "list" behavior

0.30.0 (2016-10-17)
+++++++++++++++++++

* Initial preview release. Based on API version 2016-03-30.


0.20.0 (2015-08-31)
+++++++++++++++++++

* Initial preview release. Based on API version 2015-05-01-preview.



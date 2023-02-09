# Nand tool

This project contains code to do ECC correction for NAND flash. The tool has been created because ECC configurations are varied and can have many options. We want a general tool that can perform ECC corrections on any NAND flash. The configuration of the ECC must be known and should be recorded in a configuration file (`.toml`). 

For each partition in the file system a different ECC structure can be defined and each partition will be mounted on a separate folder of the specified mount point. The mounting is done using fusepy. For a few systems the configuration files are in this repository. If no configuration file is present, the section [Structure of a Configuration File](#Structure-of-a-Configuration-File) explains how a config file should be structured. 


## Getting started

Set up your Python virtual environment and activate the environment:

```commandline
python3 -m venv venv
source ./venv/bin/activate
```

Install the linux dependencies below and install nandtool in the virtual environment:

```commandline
sudo apt install fuse python3-dev build-essential
pip install nandtool
```


## Usage

To list the available configurations:

```shell
python3 -m nandtool list
```

To use the tool to mount (an ECC corrected) image:

```shell
python3 -m nandtool mount /image -m /mountpoint -c /config
```

If mounting succeeds you will see the log message `"Mounting image /image on mount point /mountpoint with configuration /config"` appear and the process will hang. Navigate to the given mount point with another terminal session or a file browser to access the NAND partitions.

Unmounting can be done from the terminal with:

```shell
sudo umount /mountpoint
```

The logs will show show that the image was successfully unmounted and nandtool will exit.

Note that the partition is not saved to the mount point. Once you unmount, the partitions are removed. If you want to save the partition binaries, you have to do so by hand.


## Structure of a Configuration File

The [example.toml](config/example.toml) shows what a config file should look like and the different sections and parameters are explained in the comments. Setting up the config requires one to know the partitions in the NAND image. How the partion info can be found is discussed in [the next section](#NAND-Partition-Info). 

For the partitions a layout must be defined and the page size is set. The SIMPLE layout shows the required parameters for a parition with ecc correction, and the COMPLEX layout shows the additional optional parameters that can be set. The NOECC layout shows that it is also possible to extract the user data without performing ecc correction. Note that not all partitions in the image have to be listed. The nandtool will only correct and extract the partitions listed in the config file. 

The ordering of ecc bytes and ecc protected data within a page differs greatly per NAND flash. Therefore, this tool allows the user to set per byte whether it is ecc protected data, user data, or ecc code. This is done using intervals. Moreover, a page may be split up into several chunks (usually four) on which error correction needs to be performed separately. For each chunk the intervals need to be defined. 

For example, in the simple layout, we have four chunks of 512 bytes of ecc protected data at the start of the page. The user data is equal to the ecc protected data in this case. The ecc bytes for each chunk are located at the end of the page at offsets 2050, 2064, 2078, 2092, and each 13 bytes long.
In the complex layout the protected data bytes are immidiately followed by the ecc bytes, which is repeated four times. Also, the protected data intervals are different from the user data intervals. 

It is also possible to define configurations that do not perform ECC correction, but simply extract the uncorrected user data for instance. In this case simply omit the parameters that define ECC correction. Some configurations without ECC correction are provided and labeled `noecc`.

Feel free to create a merge request if you create configs for systems not yet available in this repo.


## NAND Partition Info

On QNX systems [dumpifs](https://github.com/FrancisHoogendijk/dumpifs) can be used to get insight into the partition table. First, extract the user data from the image without performing the ECC correction. This can also be done with a config file (the ones called `noecc`):

```commandline
python3 -m nandtool /image -m /mountpoint -c /config
```

Clone the [dumpifs](https://github.com/FrancisHoogendijk/dumpifs) repository and use the tool in the repo. The image in the command below is the file we just mounted with the command above.

```commandline
dumpifs -x /image -d /output_dir
```

In the output directory look for `etc/system/config/nand_partition.txt`. In this text file the offsets (in blocks) of the partitions are given.

On systems that do not run QNX, finding the partition table may involve manually delving into the binary for the information.


## Contributing

If you want develop and contribute to the tool, first fork the repository. Contributions can be submitted as a merge request. 

To get started clone the forked repository and create a virtual environment. Install poetry, necessary linux packages, and dependencies.

```commandline
sudo apt install fuse python3-dev build-essential
pip install .
```


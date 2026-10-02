---
license: apache-2.0
---

# Dataset Structure

The following directory structure is consistent across all datasets. Each geometry is assigned an unique identifier: {dataset_name}_00000000 where {dataset_name} is the name of the dataset and 00000000 is an 8-digit number starting from zero.

Each dataset has two main folders: info and stl. The info folder contains metadata about each geometry in JSON format, including geometric parameters, random rotation applied to the geometry, reverse transformation (label) in various mathematical definitions. The stl folder is divided into three subfolders containing training, validation, and test data in STL format.

```
{dataset_name}_{number_of_samples}/
|--- info
|    |--- {dataset_name}_00000000.json
|    |--- {dataset_name}_00000001.json
|--- stl
|    |--- test
|    |    |--- {dataset_name}_00000000.stl
|    |    |--- {dataset_name}_00000001.stl
|    |    ...
|    |--- train
|    |    ...
|    |--- validation
|    |    ...
```

# Cite

```latex
@article{WEN25,
	title = {Learning automatic part orientation for powder bed fusion of metal from part data},
	doi = {10.1007/s40964-025-00960-6},
	journaltitle = {Progress in Additive Manufacturing},
	author = {Wenger, Sebastian and Shevchenko, Iryna and zur Jacobsmühlen, Joschka and Krüger, Jörg and Uhlmann, Eckart},
	date = {2025-02-08},
}
```

import pytest

import matplotlib.pyplot as plt
# This import registers the 3D projection, but is otherwise unused.
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 unused import
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

import postbox.space as pb


def test_cube_creation() -> None:
    test_points = np.array(
        [(0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1)]
    ).reshape((4, 3))

    test_cube = pb.Cube(test_points)

    assert test_cube.faces.shape == (6, 4, 3)
    assert test_cube.facecolor == None
    assert test_cube.linewidths == 0.1
    assert test_cube.edgecolor == 'black'
    assert test_cube.alpha == 0.0


# TODO: Add/fill out tests!
def test_cube_creates_all_data_needed_for_visualising() -> None:
    test_points = np.array(
        [(0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1)]
    ).reshape((4, 3))
    test_cube = pb.Cube(test_points)
    poly = Poly3DCollection(test_cube.faces)
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='3d')
    plt_collection = ax.add_collection3d(poly)
    # The internal vector includes all 1s in an the implicit 4th dimension
    # TODO: Understand why this is necessary. Probably to do with 3D projections
    # or something like that.
    plt_internal_data = np.array(
        [plt_collection.axes.collections[0]._vec]
    )
    plt_internal_reshaped_data = plt_internal_data.T.reshape((6, 4, 4))

    # Add the implicit 4th dimension to the original data - all ones.
    ones = np.ones((6, 4, 1))
    original_augmented_data = np.concatenate([test_cube.faces, ones], -1)

    assert np.array_equal(original_augmented_data, plt_internal_reshaped_data)


def test_space_creation() -> None:
    points = np.array(
        [(0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1)]
    ).reshape((4, 3))
    cube = pb.Cube(points)

    space = pb.Space()
    assert space.dims is None
    assert np.array_equal(space.mean, np.zeros((3, 1)))
    assert np.array_equal(space.total, np.zeros((3, 1)))
    assert space.num_objs == 0
    assert space.primitive_counter == 0
    assert space.time_step == 0
    assert space.scene_counter == 0
    assert np.array_equal(space.cuboid_coordinates, np.zeros((10, 6, 4, 3)))
    assert space.cuboid_visual_metadata == {}
    assert space.cuboid_index is not None
    assert space.changelog == []


# def test_space_creates_valid_axes_on_render() -> None:
#     pass
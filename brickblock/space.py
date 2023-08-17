# TODO: Get isort working so we can sort these imports
from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt

# This import registers the 3D projection, but is otherwise unused.
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 unused import
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np

from brickblock.index import SpaceIndex
from brickblock.objects import Cube, Cuboid, CompositeCube


# TODO: Decide if we want to use classes for this, what details need adding to
# make these transforms useful, etc.
# TODO: Add docstrings
class SpaceStateChange:
    ...


@dataclass
class Addition(SpaceStateChange):
    timestep_id: int
    name: str | None


@dataclass
class Mutation(SpaceStateChange):
    name: str | None
    primitive_id: int | None
    timestep_id: int | None
    scene_id: int | None
    subject: np.ndarray | tuple[dict[str, Any], dict[str, Any]]


@dataclass
class Deletion(SpaceStateChange):
    timestep_id: int
    name: str | None


class Space:
    """
    Representation of a 3D coordinate space, which tracks its state over time.

    Any added objects are stored in a variety of formats, such as by coordinate
    data, by name, and various IDs. This facilitates multiple ways of querying
    them within a space.

    The space is the object that abstracts over a visualisation backend, like
    matplotlib.

    # Attributes
        dims: The dimensions of the space. This is stored for potential use with
            the camera when rendering a scene.
        mean: The mean point of the space. This is stored for potential use with
            the camera when rendering a scene.
        total: The total value per dimension of all objects. This is stored for
            potential use with the camera when rendering a scene.
        num_objs: The total number of objects in the space. Distinct primitives
            and composites each count as one object.
        primitive_counter: The total number of primitives in the space. A
            composite object can comprise of multiple primitives.
        time_step: The number of individual transforms done to the space.
        scene_counter: The number of scenes to render.
        cuboid_coordinates: The dense coordinate info for each primitive in the
            space. This has shape Nx6x4x3, where N is the number of primitives.
            Objects are stored in order of insertion.
        cuboid_visual_metadata: The visual properties for each primitive in the
            space. Objects are stored in order of insertion.
        cuboid_index: A hierarchial index of the objects inserted into the
            space.
        cuboid_names: A mapping between names and objects/primitives.
        changelog: A high-level description of each transform done to the space.
    """

    # TODO: Clarify dimensions for things being WHD or XYZ (or a mix).
    dims: np.ndarray
    mean: np.ndarray
    total: np.ndarray
    num_objs: int
    primitive_counter: int
    time_step: int
    scene_counter: int
    # TODO: Should these be classes?
    cuboid_coordinates: np.ndarray
    cuboid_visual_metadata: dict[str, list]
    cuboid_index: SpaceIndex
    cuboid_names: dict[str, tuple[list[int], list[slice]]]
    changelog: list[SpaceStateChange]

    def __init__(self) -> None:
        self.dims = np.zeros((3, 2))
        self.mean = np.zeros((3, 1))
        self.total = np.zeros((3, 1))
        self.num_objs = 0
        self.primitive_counter = 0
        self.time_step = 0
        self.scene_counter = 0
        self.cuboid_coordinates = np.zeros((10, 6, 4, 3))
        self.cuboid_visual_metadata = {}
        self.cuboid_index = SpaceIndex()
        self.cuboid_names = {}
        self.changelog = []

    def add_cube(self, cube: Cube) -> None:
        """
        Add a Cube primitive to the space.
        """
        primitive_id = self._add_cuboid_primitive(cube)
        self._add_name(cube.name, [[primitive_id], None])
        self.num_objs += 1
        self.changelog.append(Addition(self.time_step, None))
        self.time_step += 1
        self._update_bounds(slice(primitive_id, primitive_id + 1))

    def add_cuboid(self, cuboid: Cuboid) -> None:
        """
        Add a Cuboid primitive to the space.
        """
        primitive_id = self._add_cuboid_primitive(cuboid)
        self._add_name(cuboid.name, [[primitive_id], None])
        self.num_objs += 1
        self.changelog.append(Addition(self.time_step, None))
        self.time_step += 1
        self._update_bounds(slice(primitive_id, primitive_id + 1))

    def add_composite(self, composite: CompositeCube) -> None:
        """
        Add a CompositeCube object to the space.
        """
        num_cubes = composite.faces.shape[0]

        # Update bounding box
        flattened_faces = composite.faces.reshape((-1, 3))
        self.total += np.mean(flattened_faces, axis=0).reshape((3, 1))

        # We only add one to the denominator because we added a single object.
        self.mean = self.total / (self.primitive_counter + 1)

        composite_points = np.array(
            [composite.faces[0][0], composite.faces[-1][-1]]
        ).reshape((8, 3))

        x_min = np.min(composite_points[:, 0])
        x_max = np.max(composite_points[:, 0])
        z_min = np.min(composite_points[:, 1])
        z_max = np.max(composite_points[:, 1])
        y_min = np.min(composite_points[:, 2])
        y_max = np.max(composite_points[:, 2])

        composite_extrema = np.array(
            [[x_min, x_max], [z_min, z_max], [y_min, y_max]]
        ).reshape((3, 2))

        if self.primitive_counter == 0:
            dim = composite_extrema
        else:
            # Since there are multiple objects, ensure the resulting dimensions
            # of the surrounding box are the extrema of the objects within.
            dim = np.array(
                [
                    [
                        min(self.dims[i][0], composite_extrema[i][0]),
                        max(self.dims[i][1], composite_extrema[i][1]),
                    ]
                    for i in range(len(composite_extrema))
                ]
            ).reshape((3, 2))

        self.dims = dim

        # Update coordinate array
        current_no_of_entries = self.cuboid_coordinates.shape[0]
        if (self.primitive_counter + num_cubes) >= current_no_of_entries:
            # Ensure that at most one allocation is needed to encompass this
            # composite.
            while (2 * current_no_of_entries) < num_cubes:
                current_no_of_entries *= 2

            # refcheck set to False since this avoids issues with the debugger
            # referencing the array!
            self.cuboid_coordinates.resize(
                (2 * current_no_of_entries, *self.cuboid_coordinates.shape[1:]),
                refcheck=False,
            )

        base = self.primitive_counter
        offset = base + num_cubes
        self.cuboid_coordinates[base:offset] = composite.faces

        # Update visual metadata store
        for key, value in composite.get_visual_metadata().items():
            if key in self.cuboid_visual_metadata.keys():
                self.cuboid_visual_metadata[key].extend([value] * num_cubes)
            else:
                self.cuboid_visual_metadata[key] = [value] * num_cubes

        self.primitive_counter += num_cubes
        primitive_ids = slice(base, offset)

        # Add to index
        self.cuboid_index.add_composite_to_index(
            primitive_ids, self.time_step, self.scene_counter
        )

        # TODO: Consider how to implement 'styles'.
        if composite.style == "classic":
            raise NotImplementedError("Currently, styles are not supported.")
            ...

        self._add_name(composite.name, [None, [primitive_ids]])

        self.num_objs += 1
        self.changelog.append(Addition(self.time_step, None))
        self.time_step += 1
        self._update_bounds(primitive_ids)

    def _add_cuboid_primitive(self, cuboid: Cube | Cuboid) -> int:
        """
        Add a primitive to the space by updating the various indices and data
        structures, and return its ID.

        # Args
            cuboid: Primitive Cube/Cuboid to add to the space's various data
            structures.
        """
        cuboid_bounding_box = cuboid.get_bounding_box()
        cuboid_mean = np.mean(cuboid.points(), axis=0).reshape((3, 1))

        # Update the bounding box - via total, mean, and dims.
        self.total += cuboid_mean

        self.mean = self.total / (self.primitive_counter + 1)

        if self.primitive_counter == 0:
            dim = cuboid_bounding_box
        else:
            # Since there are multiple objects, ensure the resulting dimensions
            # of the surrounding box are the extrema of the objects within.
            dim = np.array(
                [
                    [
                        min(self.dims[i][0], cuboid_bounding_box[i][0]),
                        max(self.dims[i][1], cuboid_bounding_box[i][1]),
                    ]
                    for i in range(len(cuboid_bounding_box))
                ]
            ).reshape((3, 2))

        self.dims = dim

        # Update the coordinate data, resizing if necessary.
        current_no_of_entries = self.cuboid_coordinates.shape[0]
        if self.primitive_counter >= current_no_of_entries:
            # refcheck set to False since this avoids issues with the debugger
            # referencing the array!
            self.cuboid_coordinates.resize(
                (2 * current_no_of_entries, *self.cuboid_coordinates.shape[1:]),
                refcheck=False,
            )

        self.cuboid_coordinates[self.primitive_counter] = cuboid.faces

        # Update the visual metadata store.
        for key, value in cuboid.get_visual_metadata().items():
            if key in self.cuboid_visual_metadata.keys():
                self.cuboid_visual_metadata[key].append(value)
            else:
                self.cuboid_visual_metadata[key] = [value]

        self.cuboid_index.add_primitive_to_index(
            self.primitive_counter, self.time_step, self.scene_counter
        )

        # Update the primitive_counter.
        primitive_id = self.primitive_counter
        self.primitive_counter += 1

        return primitive_id

    def _add_name(
        self,
        name: str | None,
        object_ids: tuple[list[int] | None, list[slice] | None],
    ) -> None:
        """
        Add an entry for `name` for the given `object_ids`, if specified.

        It is an error to add an entry for a name that already exists.

        # Args
            name: An optional name that references each ID in `object_ids`.
            object_ids: The primitive/composite ID(s) to name. Can contain both
                primitives and composites, each composite is assumed to be
                non-empty. There must be at least one valid ID.
        """
        if name is not None:
            if name in self.cuboid_names.keys():
                raise Exception(
                    f"There already exists an object with name {name}."
                )
            if object_ids[0] is None and object_ids[1] is None:
                raise Exception(
                    "The entity to name has no IDs associated with it."
                )
            self.cuboid_names[name] = object_ids

    def _update_bounds(self, primitive_ids: slice) -> None:
        """
        Update the bounding box of the space, based on the primitives given by
        `primitive_ids`.

        Whether one or more primitives are given, the space will update its
        bounds over the extrema in both cases.

        The bounds of the space are updated regardless of whether or not the
        provided primitives are visible.

        # Args
            primitive_ids: The primitives for which coordinate data is used to
                update the bounding box of this space.
        """
        N = primitive_ids.stop - primitive_ids.start
        primitives = self.cuboid_coordinates[primitive_ids].reshape(
            (N * 6 * 4, 3)
        )
        given_mins = np.min(primitives, axis=0)
        given_maxes = np.max(primitives, axis=0)

        self.dims[:, 0] = np.minimum(self.dims[:, 0], given_mins.T)
        self.dims[:, 1] = np.maximum(self.dims[:, 1], given_maxes.T)

    # TODO: Decide how deletion should be implemented. Masking columns seem the
    # most logical, but this could be an issue for memory consumption. On the
    # other hand, 'actual deletion' would involve potentially expensive memory
    # shuffling.
    # Moreover, should you even be worrying about deletion? Masking is what you
    # really want in virtually all cases. Deletion should actually be quite rare
    # unless a user does something dumb or adds crazy numbers of objects.

    def mutate_by_coordinate(self, coordinate: np.ndarray, **kwargs) -> None:
        """
        Mutate the visual metadata of all objects - composite or primitive, with
        base vectors equal to `coordinate` - with the named arguments in
        `kwargs`.

        Primitives that are part of composites are not included - that is, if
        `coordinate` intersects with a composite on any point other than its
        base vector, none of its primitives will be updated.

        Note that the base vector is defined as the bottom-left-front-most point
        of an object, primitive or composite.

        # Args
            coordinate: The coordinate which is compared to the base vector of
                all objects in the space.
            kwargs: Sequence of named arguments that contain updated visual
                property values.
        """
        primitives_to_update, composites_to_update = self._select_by_coordinate(
            coordinate
        )
        self._mutate_by_ids(
            primitives_to_update, composites_to_update, **kwargs
        )

    def mutate_by_name(self, name: str, **kwargs) -> None:
        """
        Mutate the visual metadata of the object - composite or primitive, that
        has its name equal to `name` - with the named arguments in `kwargs`.

        # Args
            name: The name of the object in the space to update.
            kwargs: Sequence of named arguments that contain updated visual
                property values.
        """
        primitives_to_update, composites_to_update = self._select_by_name(name)
        self._mutate_by_ids(
            primitives_to_update, composites_to_update, **kwargs
        )

    def mutate_by_timestep(self, timestep: int, **kwargs) -> None:
        """
        Mutate the visual metadata of the object - composite or primitive, that
        was created at timestep `timestep` - with the named arguments in
        `kwargs`.

        # Args
            timestep: The timestep of all the objects in the space to update.
            kwargs: Sequence of named arguments that contain updated visual
                property values.
        """
        primitives_to_update, composites_to_update = self._select_by_timestep(
            timestep
        )
        self._mutate_by_ids(
            primitives_to_update, composites_to_update, **kwargs
        )

    def mutate_by_scene(self, scene: int, **kwargs) -> None:
        """
        Mutate the visual metadata of the object - composite or primitive, that
        was created in scene `scene` - with the named arguments in `kwargs`.

        # Args
            scene: The scene of all the objects in the space to update.
            kwargs: Sequence of named arguments that contain updated visual
                property values.
        """
        primitives_to_update, composites_to_update = self._select_by_scene(
            scene
        )
        self._mutate_by_ids(
            primitives_to_update, composites_to_update, **kwargs
        )

    def _mutate_by_ids(
        self, primitive_ids: list[int], composite_ids: list[slice], **kwargs
    ) -> None:
        """
        Mutate the visual metadata of all primitives and composites (given by
        `primitive_ids` and `composite_ids` respectively) with the named
        arguments in `kwargs`.

        # Args
            primitive_ids: The IDs of all the primitives in the space to update.
            composite_ids: The IDs of all the composites in the space to update.
            kwargs: Sequence of named arguments that contain updated visual
                property values.
        """
        for key in kwargs.keys():
            if key not in self.cuboid_visual_metadata.keys():
                raise KeyError(
                    "The provided key doesn't match any valid visual property."
                )
            for primitive_id in primitive_ids:
                self.cuboid_visual_metadata[key][primitive_id] = kwargs[key]
            for composite_id in composite_ids:
                N = composite_id.stop - composite_id.start
                broadcast_val = [kwargs[key]] * N
                self.cuboid_visual_metadata[key][composite_id] = broadcast_val

    def create_by_offset(
        self,
        offset: np.ndarray,
        coordinate: np.ndarray | None = None,
        name: str | None = None,
        timestep: int | None = None,
        scene: int | None = None,
        **kwargs,
    ) -> None:
        """
        Create a duplicate of an object (or objects) selected by any one of
        `coordinate`, `name`, `timestep`, or `scene`, shifted by `offset`.

        The offset is done with respect to the base vectors of the objects.

        Exactly one of `coordinate`, `name`, `timestep`, or `scene` must be set.
        The selection can refer to multiple objects - in this case, a duplicate
        is made for each object in the selection.

        Note that all objects created will be treated as having been created at
        the same timestep.

        The remaining args are used to override the inherited visual properties
        of the created objects. These will apply to all created objects - if a
        single value is given, then this is broadcast to all objects. Otherwise
        a list with the same number of created objects is given and will be
        applied in order of insertion.

        # Args
            offset: Offset by base vector, in XYZ coordinate form.
            coordinate: Optional selection, where all objects with equal base
                vectors will be selected.
            name: Optional selection, where the object with that name will be
                selected.
            timestep: Optional selection, where all objects created in that
                timestep will be selected.
            scene: Optional selection, where all objects created in that scene
                will be selected.
            kwargs: Optional visual property arguments - can be a dict with
                scalar or list of values.
        """
        exactly_one_set = (
            sum([a is not None for a in [coordinate, name, timestep, scene]])
            == 1
        )
        if not exactly_one_set:
            raise ValueError(
                "Exactly one selection argument can be set when creating "
                "objects."
            )

        if coordinate is not None:
            primitive_ids, _ = self._select_by_coordinate(coordinate)
        if name is not None:
            primitive_ids = self._select_by_name(name)
        if timestep is not None:
            primitive_ids = self._select_by_timestep(timestep)
        if scene is not None:
            primitive_ids = self._select_by_scene(scene)

        # TODO: You ideally want an index of which primitives correspond to
        # composites, if any.
        print(primitive_ids)

    def _select_by_coordinate(
        self, coordinate: np.ndarray
    ) -> tuple[list[int], list[slice]]:
        if coordinate.shape != (3,):
            raise ValueError(
                "Coordinates are three-dimensional, the input vector should be "
                "3D."
            )

        # Map the coordinate to the correct representation.
        # TODO: Decouple the user from a fixed basis.
        w, h, d = coordinate
        coordinate = np.array([w, d, h])

        # First gather the IDs of primitive entries that match the coordinate.
        matching_base_vectors = []
        primitives_to_update, composites_to_update = [], []

        for idx in range(self.primitive_counter):
            primitive = self.cuboid_coordinates[idx]
            if np.array_equal(primitive[0, 0], coordinate):
                matching_base_vectors.append(idx)

        # You can assume all indices are either landing on the first primitive
        # of a composite (a match) or a distinct primitive, since otherwise
        # you don't consider it a match anyway. That means you can just compare
        # against the first value of the slices in the composite buffer.

        primitive_id = next(self.cuboid_index.primitives(), None)
        composite_slice = next(self.cuboid_index.composites(), None)

        # For each index, check if it's a primitive or composite. If it is,
        # add it to the relevant output buffer/increment the relevant iterator.
        # If the relevant iterator is exhausted, use a default of None.
        for idx in matching_base_vectors:
            if primitive_id is not None and primitive_id == idx:
                primitives_to_update.append(primitive_id)
                primitive_id = next(self.cuboid_index.primitives(), None)
            if composite_slice is not None and composite_slice.start == idx:
                composites_to_update.append(composite_slice)
                composite_slice = next(self.cuboid_index.composites(), None)

        return primitives_to_update, composites_to_update

    def _select_by_name(self, name: str) -> tuple[list[int], list[slice]]:
        if name not in self.cuboid_names.keys():
            raise ValueError("The provided name does not exist in this space.")

        primitive_ids, composite_ids = self.cuboid_names[name]

        primitive_ids = primitive_ids if primitive_ids is not None else []
        composite_ids = composite_ids if composite_ids is not None else []

        return primitive_ids, composite_ids

    def _select_by_timestep(
        self, timestep: int
    ) -> tuple[list[int], list[slice]]:
        if (timestep < 0) or (timestep > self.time_step):
            raise ValueError("The provided timestep is invalid in this space.")

        primitive_ids = self.cuboid_index.get_primitives_by_timestep(timestep)
        composite_ids = self.cuboid_index.get_composites_by_timestep(timestep)

        return primitive_ids, composite_ids

    def _select_by_scene(self, scene: int) -> tuple[list[int], list[slice]]:
        if (scene < 0) or (scene > self.scene_counter):
            raise ValueError("The provided scene ID is invalid in this space.")

        primitive_ids = self.cuboid_index.get_primitives_by_scene(scene)
        composite_ids = self.cuboid_index.get_composites_by_scene(scene)

        return primitive_ids, composite_ids

    def snapshot(self) -> None:
        """
        Store the current state of the space as a scene, used for rendering.

        Note that valid scenes must have 1+ transforms - i.e. adding,
        deleting, or mutating an object, must be present in a scene.
        """
        expected_num_scenes = self.scene_counter + 1
        if not self.cuboid_index.current_scene_is_valid(expected_num_scenes):
            raise Exception(
                "A snapshot must include at least one addition, mutation, or "
                "deletion in the given scene."
            )
        self.scene_counter += 1

    # TODO: Decide whether passing the Axes or having it be fully constructed by
    # brickblock is a good idea - memory management could be a problem.
    # TODO: It seems controlling the azimuth and elevation parameters (which are
    # handily configurable!) is what you need for adjusting the camera.
    # TODO: plt.show shows each figure generated by render(), rather than only
    # the last one (though it shows the last one first). Can this be fixed?
    # (Yes - you are being an idiot).
    def render(self) -> tuple[plt.Figure, plt.Axes]:
        """
        Render every scene in the space with a matplotlib Axes, and return the
        figure-axes pair.
        """
        fig = plt.figure(figsize=(10, 7))
        fig.subplots_adjust(
            left=0, bottom=0, right=1, top=1, wspace=0.0, hspace=0.0
        )
        ax = fig.add_subplot(111, projection="3d")
        # Remove everything except the objects to display.
        ax.set_axis_off()

        # TODO: This logic really belongs in a `stream()` function. The render
        # method should just get all primitive_ids and then render everything
        # from the coordinates and visual_metadata.
        for scene_id in range(self.scene_counter + 1):
            primitives_for_scene = self.cuboid_index.get_primitives_by_scene(
                scene_id
            )
            composites_for_scene = self.cuboid_index.get_composites_by_scene(
                scene_id
            )
            for primitive in primitives_for_scene:
                ax = self._populate_ax_with_primitive(ax, primitive)
            for composite in composites_for_scene:
                ax = self._populate_ax_with_composite(ax, composite)

        # Use the space's bounds to update the camera and view.
        # This is very janky but at least ensures everything is in view.
        # One way this could be fixed would be to reorient everything so that
        # aiming at the origin actually works. Essentially you take the
        # difference between the center of the bounding box of the space, and
        # the origin, and shift everything by the negative difference.
        # The problem with this solution is a) it involves a transform over
        # everything and b) would mean the user cannot turn on the axes to debug
        # things as effectively. Potentially this could be explained in some
        # docs though.
        max_val = max(list(self.dims.flatten()))
        ax.set_xlim(-max_val, max_val)
        ax.set_ylim(-max_val, max_val)
        ax.set_zlim(-max_val, max_val)

        return fig, ax

    def _populate_ax_with_primitive(
        self,
        ax: plt.Axes,
        primitive_id: int,
    ) -> plt.Axes:
        """
        Add the primitive with `primitive_id` to the `ax`, including both
        coordinate and visual metadata.

        # Args
            ax: The matplotlib Axes object to add the primitive to.
            primitive_id: The ID of the primitive to add.
        """
        # Create the object for matplotlib ingestion.
        matplotlib_like_cube = Poly3DCollection(
            self.cuboid_coordinates[primitive_id]
        )
        # Set the visual properties first - check if these can be moved
        # into the Poly3DCollection constructor instead.
        visual_properties = {
            k: self.cuboid_visual_metadata[k][primitive_id]
            for k in self.cuboid_visual_metadata.keys()
        }
        matplotlib_like_cube.set_facecolor(visual_properties["facecolor"])
        matplotlib_like_cube.set_linewidths(visual_properties["linewidth"])
        matplotlib_like_cube.set_edgecolor(visual_properties["edgecolor"])
        matplotlib_like_cube.set_alpha(visual_properties["alpha"])
        ax.add_collection3d(matplotlib_like_cube)

        return ax

    def _populate_ax_with_composite(
        self, ax: plt.Axes, primitive_ids: slice
    ) -> plt.Axes:
        """
        Add the composite with `primitive_ids` to the `ax`, including both
        coordinate and visual metadata.

        # Args
            ax: The matplotlib Axes object to add the primitives to.
            primitive_ids: The IDs of all the primitives to add.
        """
        for primitive_id in range(primitive_ids.start, primitive_ids.stop):
            # Create the object for matplotlib ingestion.
            matplotlib_like_cube = Poly3DCollection(
                self.cuboid_coordinates[primitive_id]
            )
            # Set the visual properties first - check if these can be moved
            # into the Poly3DCollection constructor instead.
            visual_properties = {
                k: self.cuboid_visual_metadata[k][primitive_id]
                for k in self.cuboid_visual_metadata.keys()
            }
            matplotlib_like_cube.set_facecolor(visual_properties["facecolor"])
            matplotlib_like_cube.set_linewidths(visual_properties["linewidth"])
            matplotlib_like_cube.set_edgecolor(visual_properties["edgecolor"])
            matplotlib_like_cube.set_alpha(visual_properties["alpha"])
            ax.add_collection3d(matplotlib_like_cube)

        return ax

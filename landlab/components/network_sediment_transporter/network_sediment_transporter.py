#!/usr/env/python

"""
Landlab component that simulates the transport of bed material
sediment through a 1-D river network, while tracking the resulting changes
in bed material grain size and river bed elevation. Model framework
described in Czuba (2018). Additions include: particle abrasion, variable
active layer thickness (Wong et al., 2007).

Fixes that need to happen:

    -- Check abrasion exponent units (per km or per m?)

    -- Flow depth -- double check to make sure we're going through flow depth array correctly

    -- JC: I found two items that I think should be changed in the _calc_transport_wilcock_crowe and I made these changes
            - frac_parcels was the inverse of what it should be so instead of a fraction it was a number >1
            - in unpacking W* we had a (1-frac_sand) this was fine when we were treating sand and gravel separately,
              but now that we are treating all parcels together, I no longer think this should be there, because if we are trying
              to move a sand parcel then this (1-frac_sand) does not make sense. I think this is  now equivalent to the original WC2003.
              Before it was equivalent to WC2003 as implemented in Cui TUGS formulation.
            - finally, I added the calculation of a parcel velocity instead of the travel time. I think this is
              better suited to the parcel centric spirit of the code. It was also needed to simplify move_parcel_downstream
              Plus, I think one day we will have a better way to parameterize parcel virtual velocity and this will then be
              easy to incorporate/update.

.. codeauthor:: Allison Pfeiffer, Katy Barnhart, Jon Czuba

Created on Tu May 8, 2018
Last edit ---
"""

import numpy as np

# %% Import Libraries
from landlab import Component
from landlab.components import FlowDirectorSteepest
from landlab.data_record import DataRecord
from landlab.grid.network import NetworkModelGrid

_SUPPORTED_TRANSPORT_METHODS = ["WilcockCrowe"]

_OUT_OF_NETWORK = NetworkModelGrid.BAD_INDEX - 1

_REQUIRED_PARCEL_ATTRIBUTES = [
    "time_arrival_in_link",
    "abrasion_rate",
    "density",
    "active_layer",
    "location_in_link",
    "D",
    "volume",
]

_ACTIVE = 1
_INACTIVE = 0


class NetworkSedimentTransporter(Component):
    """
    Landlab component that simulates the transport of bed material
    sediment through a 1-D river network, while tracking the resulting changes
    in bed material grain size and river bed elevation. Model framework
    described in Czuba (2018). Additions include: particle abrasion, variable
    active layer thickness (Wong et al., 2007).


    **Usage:**
    Option 1 - Basic::
        NetworkSedimentTransporter(grid,
                             parcels,
                             transporter = asdfasdf,
                             discharge,
                             channel_geometry
                             )

    Examples
    ----------
    >>> import numpy as np
    >>> from landlab.components import FlowDirectorSteepest, NetworkSedimentTransporter
    >>> from landlab import NetworkModelGrid
    >>> from landlab.data_record import DataRecord
    >>> _OUT_OF_NETWORK = NetworkModelGrid.BAD_INDEX - 1

    The NetworkSedimentTransporter moves "parcels" of sediment down a network
    based on a given flow and a given sediment transport formulation. The river
    network is represented by a landlab NetworkModelGrid. Flow direction in the
    network is determined using a landlab flow director. Sediment parcels are
    represented as items within a landlab ``DataRecord``.

    Create a ``NetworkModelGrid`` to represent the river channel network. In this
    case, the grid is a single line of 4 nodes connected by 3 links. Each link represents a reach of river.
    >>> y_of_node = (0, 0, 0, 0)
    >>> x_of_node = (0, 100, 200, 300)
    >>> nodes_at_link = ((0,1), (1,2), (2,3))

    >>> nmg = NetworkModelGrid((y_of_node, x_of_node), nodes_at_link)

    Add required channel and topographic variables to the NetworkModelGrid.

    >>> _ = nmg.add_field("bedrock__elevation", [3., 2., 1., 0.], at="node") # m
    >>> _ = nmg.add_field("reach_length", [100., 100., 100.], at="link")  # m
    >>> _ = nmg.add_field("channel_width", (15 * np.ones(nmg.size("link"))), at="link")

    Add ``topographic__elevation`` to the grid because the ``FlowDirectorSteepest``
    will look to it to determine the direction of sediment transport through the
    network. Each time we run the ``NetworkSedimentTransporter`` the
    topography will be updated based on the bedrock elevation and the
    distribution of alluvium.

    >>> _ = nmg.add_field("topographic__elevation", np.copy(nmg.at_node["bedrock__elevation"]), at="node")

    Run ``FlowDirectorSteepest`` to determine the direction of sediment transport through the network.
    >>> flow_director = FlowDirectorSteepest(nmg)
    >>> flow_director.run_one_step()

    Define the starting time and the number of timesteps for this model run.
    >>> timesteps = 10
    >>> time = [0.0]

    Define the flow depth for each link and timestep.
    >>> example_flow_depth = (
    ...     np.tile(2, (nmg.number_of_links)) *
    ...     np.tile(1, (timesteps + 1, 1))) # 2 meter flow depth

    Define the sediment characteristics that will be used to create the parcels ``DataRecord``
    >>> items = {"grid_element": "link",
    ...          "element_id": np.array([[0]])}

    >>> variables = {
    ...     "starting_link": (["item_id"], np.array([0])),
    ...     "abrasion_rate": (["item_id"], np.array([0])),
    ...     "density": (["item_id"], np.array([2650])),
    ...     "time_arrival_in_link": (["item_id", "time"], np.array([[0]])),
    ...     "active_layer": (["item_id", "time"], np.array([[1]])),
    ...     "location_in_link": (["item_id", "time"], np.array([[0]])),
    ...     "D": (["item_id", "time"], np.array([[0.05]])),
    ...     "volume": (["item_id", "time"], np.array([[1]])),
    ... }

    Create the sediment parcel DataRecord. In this case, we are creating a single
    sediment parcel with all of the required attributes.
    >>> one_parcel = DataRecord(
    ...     nmg,
    ...     items=items,
    ...     time=time,
    ...     data_vars=variables,
    ...     dummy_elements={"link": [_OUT_OF_NETWORK]},
    ... )

    Instantiate the model run

    >>> nst = NetworkSedimentTransporter(
    ...         nmg,
    ...         one_parcel,
    ...         flow_director,
    ...         example_flow_depth,
    ...         bed_porosity=0.03,
    ...         g=9.81,
    ...         fluid_density=1000,
    ...         transport_method="WilcockCrowe",
    ...     )

    >>> dt = 60  # (seconds) 1 min timestep

    Run the model

    >>> for t in range(0, (timesteps * dt), dt):
    ...     nst.run_one_step(dt)

    We can the link location of the parcel at each timestep
    >>> print(one_parcel.dataset.element_id.values)
    [[ 0.  0.  0.  0.  0.  1.  1.  1.  1.  1.  2.]]

    """

    _name = "NetworkSedimentTransporter"
    __version__ = "1.0"

    _info = {
        "bedrock__elevation": {
            "dtype": float,
            "intent": "in",
            "optional": False,
            "units": "m",
            "mapping": "node",
            "doc": "elevation of the bedrock surface",
        },
        "channel_slope": {
            "dtype": float,
            "intent": "out",
            "optional": False,
            "units": "m/m",
            "mapping": "link",
            "doc": "Slope of the river channel through each reach",
        },
        "channel_width": {
            "dtype": float,
            "intent": "in",
            "optional": False,
            "units": "m",
            "mapping": "link",
            "doc": "Flow width of the channel, assuming constant width",
        },
        "reach_length": {
            "dtype": float,
            "intent": "in",
            "optional": False,
            "units": "m",
            "mapping": "link",
            "doc": "Length of each reach",
        },
        "topographic__elevation": {
            "dtype": float,
            "intent": "out",
            "optional": False,
            "units": "m",
            "mapping": "node",
            "doc": "Land surface topographic elevation",
        },
    }

    def __init__(
        self,
        grid,
        parcels,
        flow_director,
        flow_depth,
        bed_porosity=0.3,
        g=9.81,
        fluid_density=1000.0,
        transport_method="WilcockCrowe",
    ):
        """
        Parameters
        ----------
        grid: NetworkModelGrid
            A landlab network model grid in which links are stream channel
            segments.
        parcels: DataRecord
            A landlab DataRecord describing the characteristics and location of
            sediment "parcels".

            Either put more information about parcels here or put it above and
            reference it here.

        flow_director: FlowDirectorSteepest
            A landlab flow director. Currently, must be FlowDirectorSteepest.
        flow_depth: float, numpy array of shape (timesteps,links)
            Flow depth of water in channel at each link at each timestep. (m)
        bed_porosity: float, optional
            Proportion of void space between grains in the river channel bed.
            Default value is 0.3.
        g: float, optional
            Acceleration due to gravity. Default value is 9.81 (m/s^2)
        fluid_density: float, optional
            Density of the fluid (generally, water) in which sediment is
            moving. Default value is 1000 (kg/m^3)
        transport_method: string
            Sediment transport equation option. Default (and currently only)
            option is "WilcockCrowe".
        """
        if not isinstance(grid, NetworkModelGrid):
            msg = "NetworkSedimentTransporter: grid must be NetworkModelGrid"
            raise ValueError(msg)

        # run super. this will check for required inputs specified by _info
        super(NetworkSedimentTransporter, self).__init__(grid)

        # check key information about the parcels, including that all required
        # attributes are present.
        if not isinstance(parcels, DataRecord):
            msg = (
                "NetworkSedimentTransporter: parcels must be an instance"
                "of DataRecord"
            )
            raise ValueError(msg)

        for rpa in _REQUIRED_PARCEL_ATTRIBUTES:
            if rpa not in parcels.dataset:
                msg = "NetworkSedimentTransporter: {rpa} must be assigned to the parcels".format(
                    rpa=rpa
                )
                raise ValueError(msg)

        # save key information about the parcels.
        self._parcels = parcels
        self._num_parcels = self._parcels.number_of_items
        self._parcel_attributes = [
            "time_arrival_in_link",
            "active_layer",
            "location_in_link",
            "D",
            "volume",
        ]

        # assert that the flow director is a component and is of type
        # FlowDirectorSteepest
        if not isinstance(flow_director, FlowDirectorSteepest):
            msg = (
                "NetworkSedimentTransporter: flow_director must be "
                "FlowDirectorSteepest."
            )
            raise ValueError(msg)

        # save reference to flow director and specified flow depth
        self._fd = flow_director
        self._flow_depth = flow_depth

        # verify and save the bed porosity.
        if not 0 <= bed_porosity < 1:
            msg = "NetworkSedimentTransporter: bed_porosity must be" "between 0 and 1"
            raise ValueError(msg)
        self._bed_porosity = bed_porosity

        # save or create other key properties.
        self._g = g
        self._fluid_density = fluid_density
        self._time_idx = 0
        self._time = 0.0
        self._distance_traveled_cumulative = np.zeros([self._num_parcels])

        # check the transport method is valid.
        if transport_method in _SUPPORTED_TRANSPORT_METHODS:
            self._transport_method = transport_method
        else:
            msg = "NetworkSedimentTransporter: Valid transport method not supported."
            raise ValueError(msg)

        # update the update_transport_time function to be the correct function
        # for the transport method.
        if self._transport_method == "WilcockCrowe":
            self._update_transport_time = self._calc_transport_wilcock_crowe

        # save reference to key fields
        self._width = self._grid.at_link["channel_width"]

        # create field for channel_slope and topographic__elevation if they
        # don't yet exist.
        self.initialize_output_fields()
        self._channel_slope = self._grid.at_link["channel_slope"]
        self._topographic__elevation = self._grid.at_node["topographic__elevation"]

        # Adjust topographic elevation based on the parcels present.
        # Note that at present FlowDirector is just used for network connectivity.

        # get alluvium depth and calculate topography from br+alluvium, then update slopes.
        self._create_new_parcel_time()
        self._partition_active_and_storage_layers()
        self._adjust_node_elevation()
        self._update_channel_slopes()

    @property
    def time(self):
        """Return current time."""
        return self._time

    def _create_new_parcel_time(self):
        """ If we are going to track parcels through time in DataRecord, we
        need to add a new time column to the parcels dataframe. This method simply
        copies over the attributes of the parcels from the former timestep.
        Attributes will be updated over the course of this step.
        """

        if self._time_idx != 0:

            self._parcels.add_record(time=[self._time])

            self._parcels.ffill_grid_element_and_id()

            for at in self._parcel_attributes:
                self._parcels.dataset[at].values[
                    :, self._time_idx
                ] = self._parcels.dataset[at].values[:, self._time_idx - 1]

        self._find_now = self._parcels.dataset.time == self._time
        self._this_timesteps_parcels = np.zeros_like(
            self._parcels.dataset.element_id, dtype=bool
        )
        self._this_timesteps_parcels[:, -1] = True

        self._parcels_off_grid = (
            self._parcels.dataset.element_id[:, -1] == _OUT_OF_NETWORK
        )
        self._this_timesteps_parcels[self._parcels_off_grid, -1] = False

        self._num_parcels = self._parcels.number_of_items
        # ^ needs to run just in case we've added more parcels

    def _update_channel_slopes(self):
        """Re-calculate channel slopes during each timestep."""

        for i in range(self._grid.number_of_links):

            upstream_node_id = self._fd.upstream_node_at_link()[i]
            downstream_node_id = self._fd.downstream_node_at_link()[i]

            self._channel_slope[i] = _recalculate_channel_slope(
                self._grid.at_node["topographic__elevation"][upstream_node_id],
                self._grid.at_node["topographic__elevation"][downstream_node_id],
                self._grid.at_link["reach_length"][i],
            )

    def _partition_active_and_storage_layers(self, **kwds):
        """For each parcel in the network, determines whether it is in the
        active or storage layer during this timestep, then updates node
        elevations.
        """

        vol_tot = self._parcels.calc_aggregate_value(
            np.sum, "volume", at="link", filter_array=self._this_timesteps_parcels
        )
        vol_tot[np.isnan(vol_tot) == 1] = 0

        # Wong et al. (2007) approximation for active layer thickness.
        # NOTE: calculated using grain size and grain density calculated for
        # the active layer grains in each link at the **previous** timestep.
        # This circumvents the need for an iterative scheme to determine grain
        # size of the active layer before determining which grains are in the
        # active layer.

        if self._time_idx == 0:
            # In the first full timestep, we need to calc grain size & rho_sed.
            # Assume all parcels are in the active layer for the purposes of
            # grain size and mean sediment density calculations

            # FUTURE: make it possible to circumvent this if mean grain size
            # has already been calculated (e.g. during 'zeroing' runs)
            Linkarray = self._parcels.dataset.element_id[
                :, self._time_idx
            ].values  # current link of each parcel
            Darray = self._parcels.dataset.D[:, self._time_idx]
            Rhoarray = self._parcels.dataset.density.values
            Volarray = self._parcels.dataset.volume[:, self._time_idx].values

            d_mean_active = np.nan * np.zeros(self._grid.number_of_links)
            rhos_mean_active = np.nan * np.zeros(self._grid.number_of_links)

            for i in range(self._grid.number_of_links):
                d_i = Darray[Linkarray == i]
                vol_i = Volarray[Linkarray == i]
                rhos_i = Rhoarray[Linkarray == i]
                vol_tot_i = np.sum(vol_i)

                d_mean_active[i] = np.sum(d_i * vol_i) / (vol_tot_i)
                self.d_mean_active = d_mean_active

                rhos_mean_active[i] = np.sum(rhos_i * vol_i) / (vol_tot_i)
                self._rhos_mean_active = rhos_mean_active

        tau = (
            self._fluid_density
            * self._g
            * self._grid.at_link["channel_slope"]
            * self._flow_depth[self._time_idx, :]
        )

        taustar = tau / (
            (self._rhos_mean_active - self._fluid_density)
            * self._g
            * self.d_mean_active
        )

        self._active_layer_thickness = (
            0.515 * self.d_mean_active * (3.09 * (taustar - 0.0549) ** 0.56)
        )  # in units of m

        self._active_layer_thickness[
            np.isnan(self._active_layer_thickness) == 1
        ] = np.average(
            self._active_layer_thickness[np.isnan(self._active_layer_thickness) == 0]
        )  # assign links with no parcels an average value

        if np.sum(np.isfinite(self._active_layer_thickness)) == 0:
            self._active_layer_thickness = 0.03116362 * np.ones(
                np.shape(self._active_layer_thickness)
            )
            # handles the case of the first timestep -- assigns a modest value

        capacity = (
            self._grid.at_link["channel_width"]
            * self._grid.at_link["reach_length"]
            * self._active_layer_thickness
        )  # in units of m^3

        for i in range(self._grid.number_of_links):

            if vol_tot[i] > 0:  # only do this check capacity if parcels are in link

                # First In Last Out.
                parcel_id_thislink = np.where(
                    self._parcels.dataset.element_id[:, self._time_idx] == i
                )[0]

                time_arrival_sort = np.flip(
                    np.argsort(
                        self._parcels.get_data(
                            time=[self._time],
                            item_id=parcel_id_thislink,
                            data_variable="time_arrival_in_link",
                        ),
                        0,
                    )
                )

                parcel_id_time_sorted = parcel_id_thislink[time_arrival_sort]

                cumvol = np.cumsum(
                    self._parcels.dataset.volume[parcel_id_time_sorted, self._time_idx]
                )

                idxinactive = np.where(cumvol > capacity[i])
                make_inactive = parcel_id_time_sorted[idxinactive]

                self._parcels.set_data(
                    time=[self._time],
                    item_id=parcel_id_thislink,
                    data_variable="active_layer",
                    new_value=_ACTIVE,
                )

                self._parcels.set_data(
                    time=[self._time],
                    item_id=make_inactive,
                    data_variable="active_layer",
                    new_value=_INACTIVE,
                )

        # Update Node Elevations

        # set active here. reference it below in wilcock crowe
        self._active_parcel_records = (
            self._parcels.dataset.active_layer == _ACTIVE
        ) * (self._this_timesteps_parcels)

        # print("active_parcel_records",self._active_parcel_records)

        if np.any(self._active_parcel_records):
            vol_act = self._parcels.calc_aggregate_value(
                np.sum, "volume", at="link", filter_array=self._active_parcel_records
            )
            vol_act[np.isnan(vol_act) == 1] = 0

        else:
            vol_act = np.zeros_like(vol_tot)

        self._vol_stor = (vol_tot - vol_act) / (1 - self._bed_porosity)

    # %%
    def _adjust_node_elevation(self):
        """Adjusts slope for each link based on parcel motions from last
        timestep and additions from this timestep.
        """

        number_of_contributors = np.sum(
            self._fd.flow_link_incoming_at_node() == 1, axis=1
        )
        downstream_link_id = self._fd.link_to_flow_receiving_node
        # USED TO BE      downstream_link_id = self._fd.link_to_flow_receiving_node[
        #            self._fd.downstream_node_at_link()
        #        ]
        upstream_contributing_links_at_node = np.where(
            self._fd.flow_link_incoming_at_node() == 1, self._grid.links_at_node, -1
        )

        #        print("number of contributing links", number_of_contributors)
        #        print("downstream link id", downstream_link_id)
        #        print("upstream contributing links", upstream_contributing_links_at_node)

        # Update the node topographic elevations depending on the quantity of stored sediment
        for n in range(self._grid.number_of_nodes):

            if number_of_contributors[n] > 0:  # we don't update head node elevations

                upstream_links = upstream_contributing_links_at_node[n]
                real_upstream_links = upstream_links[
                    upstream_links != self._grid.BAD_INDEX
                ]
                width_of_upstream_links = self._grid.at_link["channel_width"][
                    real_upstream_links
                ]
                length_of_upstream_links = self._grid.at_link["reach_length"][
                    real_upstream_links
                ]

                #                ALERT: Moved this to the "else" statement below. AP 11/11/19
                #                length_of_downstream_link = self._grid.at_link["reach_length"][
                #                    downstream_link_id
                #                ][n]
                #                width_of_downstream_link = self._grid.at_link["channel_width"][
                #                    downstream_link_id
                #                ][n]

                if (
                    downstream_link_id[n] == self._grid.BAD_INDEX
                ):  # I'm sure there's a better way to do this, but...
                    length_of_downstream_link = 0
                    width_of_downstream_link = 0
                else:
                    length_of_downstream_link = self._grid.at_link["reach_length"][
                        downstream_link_id
                    ][n]
                    width_of_downstream_link = self._grid.at_link["channel_width"][
                        downstream_link_id
                    ][n]

                #                print("Downstream link id = ",downstream_link_id)
                #                print("We are looking at node ",n, ".  We are pointing to downstream link number ",
                #                      downstream_link_id[n], " .  And we are pointing to upstream link number(s)",
                #                      real_upstream_links)

                alluvium__depth = _calculate_alluvium_depth(
                    self._vol_stor[downstream_link_id][n],
                    width_of_upstream_links,
                    length_of_upstream_links,
                    width_of_downstream_link,
                    length_of_downstream_link,
                    self._bed_porosity,
                )

                #                print("alluvium depth = ",alluvium__depth)
                #                print("Volume stored at n = ",n,"=",self._vol_stor[downstream_link_id][n])
                #                print("Denomenator",np.sum(width_of_upstream_links * length_of_upstream_links) + width_of_downstream_link * length_of_downstream_link)
                #
                self._grid.at_node["topographic__elevation"][n] = (
                    self._grid.at_node["bedrock__elevation"][n] + alluvium__depth
                )

    def _calc_transport_wilcock_crowe(self):
        """Method to determine the transport time for each parcel in the active
        layer using a sediment transport equation.

        Note: could have options here (e.g. Wilcock and Crowe, FLVB, MPM, etc)
        """
        # parcel attribute arrays from DataRecord

        Darray = self._parcels.dataset.D[:, self._time_idx]
        Activearray = self._parcels.dataset.active_layer[:, self._time_idx].values
        Rhoarray = self._parcels.dataset.density.values
        Volarray = self._parcels.dataset.volume[:, self._time_idx].values
        Linkarray = self._parcels.dataset.element_id[
            :, self._time_idx
        ].values  # link that the parcel is currently in

        R = (Rhoarray - self._fluid_density) / self._fluid_density

        # parcel attribute arrays to populate below
        frac_sand_array = np.zeros(self._num_parcels)
        vol_act_array = np.zeros(self._num_parcels)
        Sarray = np.zeros(self._num_parcels)
        Harray = np.zeros(self._num_parcels)
        Larray = np.zeros(self._num_parcels)
        D_mean_activearray = np.zeros(self._num_parcels) * (np.nan)
        active_layer_thickness_array = np.zeros(self._num_parcels) * np.nan
        #        rhos_mean_active = np.zeros(self._num_parcels)
        #        rhos_mean_active.fill(np.nan)
        self._Ttimearray = np.zeros(self._num_parcels)
        # ^ Ttimearray is the time to move through the entire length of a link
        self._pvelocity = np.zeros(self._num_parcels)
        # ^ pvelocity is the parcel virtual velocity = link length / link travel time

        # Calculate bed statistics for all of the links
        vol_tot = self._parcels.calc_aggregate_value(
            np.sum, "volume", at="link", filter_array=self._find_now
        )
        vol_tot[np.isnan(vol_tot) == 1] = 0

        if np.any(self._active_parcel_records):
            vol_act = self._parcels.calc_aggregate_value(
                np.sum, "volume", at="link", filter_array=self._active_parcel_records
            )
            vol_act[np.isnan(vol_act) == 1] = 0

        else:
            vol_act = np.zeros_like(vol_tot)

        # find active sand.
        findactivesand = (
            self._parcels.dataset.D < 0.002
        ) * self._active_parcel_records  # since find active already sets all prior timesteps to False, we can use D for all timesteps here.

        if np.any(findactivesand):
            # print("there's active sand!")
            vol_act_sand = self._parcels.calc_aggregate_value(
                np.sum, "volume", at="link", filter_array=findactivesand
            )
            vol_act_sand[np.isnan(vol_act_sand)] = 0
        else:
            vol_act_sand = np.zeros(self._grid.number_of_links)

        frac_sand = np.zeros_like(vol_act)
        frac_sand[vol_act != 0] = vol_act_sand[vol_act != 0] / vol_act[vol_act != 0]
        frac_sand[np.isnan(frac_sand)] = 0

        # Calc attributes for each link, map to parcel arrays
        for i in range(self._grid.number_of_links):

            active_here = np.where(np.logical_and(Linkarray == i, Activearray == 1))[0]
            d_act_i = Darray[active_here]
            vol_act_i = Volarray[active_here]
            rhos_act_i = Rhoarray[active_here]
            vol_act_tot_i = np.sum(vol_act_i)
            # ^ this behaves as expected. filterarray to create vol_tot above does not. --> FIXED?
            self.d_mean_active[i] = np.sum(d_act_i * vol_act_i) / (vol_act_tot_i)
            if vol_act_tot_i > 0:
                self._rhos_mean_active[i] = np.sum(rhos_act_i * vol_act_i) / (
                    vol_act_tot_i
                )
            else:
                self._rhos_mean_active[i] = np.nan
            D_mean_activearray[Linkarray == i] = self.d_mean_active[i]
            frac_sand_array[Linkarray == i] = frac_sand[i]
            vol_act_array[Linkarray == i] = vol_act[i]
            Sarray[Linkarray == i] = self._grid.at_link["channel_slope"][i]
            Harray[Linkarray == i] = self._flow_depth[self._time_idx, i]
            Larray[Linkarray == i] = self._grid.at_link["reach_length"][i]
            active_layer_thickness_array[Linkarray == i] = self._active_layer_thickness[
                i
            ]

        Sarray = np.squeeze(Sarray)
        Harray = np.squeeze(Harray)
        Larray = np.squeeze(Larray)
        frac_sand_array = np.squeeze(frac_sand_array)

        # Wilcock and Crowe calculate transport for all parcels (active and inactive)
        self.taursg = _calculate_reference_shear_stress(
            self._fluid_density, R, self._g, D_mean_activearray, frac_sand_array
        )

        #        print("d_mean_active = ", d_mean_active)
        #        print("taursg = ", taursg)

        # frac_parcel should be the fraction of parcel volume in the active layer volume
        # frac_parcel = vol_act_array / Volarray
        # ^ This is not a fraction
        # Instead I think it should be this but CHECK CHECK
        frac_parcel = np.nan * np.zeros_like(Volarray)
        frac_parcel[vol_act_array != 0] = (
            Volarray[vol_act_array != 0] / vol_act_array[vol_act_array != 0]
        )

        b = 0.67 / (1 + np.exp(1.5 - Darray / D_mean_activearray))

        tau = self._fluid_density * self._g * Harray * Sarray
        tau = np.atleast_1d(tau)

        taur = self.taursg * (Darray / D_mean_activearray) ** b
        tautaur = tau / taur
        tautaur_cplx = tautaur.astype(np.complex128)
        # ^ work around needed b/c np fails with non-integer powers of negative numbers

        W = 0.002 * np.power(tautaur_cplx.real, 7.5)
        W[tautaur >= 1.35] = 14 * np.power(
            (1 - (0.894 / np.sqrt(tautaur_cplx.real[tautaur >= 1.35]))), 4.5
        )
        W = W.real

        active_parcel_idx = Activearray == _ACTIVE
        # compute parcel virtual velocity, m/s
        self._pvelocity[active_parcel_idx] = (
            W[active_parcel_idx]
            * (tau[active_parcel_idx] ** (3. / 2.))
            * frac_parcel[active_parcel_idx]
            / (self._fluid_density ** (3. / 2.))
            / self._g
            / R[active_parcel_idx]
            / active_layer_thickness_array[active_parcel_idx]
        )

        self._active_layer_thickness_array = active_layer_thickness_array

        self._pvelocity[np.isnan(self._pvelocity)] = 0

        # Assign those things to the grid -- might be useful for plotting later...?
        self._grid.at_link["sediment_total_volume"] = vol_tot
        self._grid.at_link["sediment__active__volume"] = vol_act
        self._grid.at_link["sediment__active__sand_fraction"] = frac_sand

    def _move_parcel_downstream(self, dt):
        """Method to update parcel location for each parcel in the active
        layer.
        """
        # determine where parcels are starting
        current_link = self._parcels.dataset.element_id[
            :, self._time_idx
        ]

        # determine location within link where parcels are starting.
        location_in_link = self._parcels.dataset.location_in_link[
            :, self._time_idx
        ]

        # determine how far each parcel needs to travel this timestep.
        distance_to_travel_this_timestep = (
            self._pvelocity * dt
        )  # total distance traveled in dt at parcel virtual velocity
        # ^ movement in current and any DS links at this dt is at the same velocity as in the current link
        # ... perhaps modify in the future(?) or ensure this type of travel is kept to a minimum
        # ... or display warnings or create a log file when the parcel jumps far in the next DS link

        # Accumulate the total distance traveled by a parcel for abrasion rate
        # calculations.
        if np.size(self._distance_traveled_cumulative) != np.size(
            distance_to_travel_this_timestep
        ):
            dist_array = distance_to_travel_this_timestep
            dist_array[: self._num_parcels] += distance_to_travel_this_timestep
            self._distance_traveled_cumulative = dist_array
        else:
            self._distance_traveled_cumulative += distance_to_travel_this_timestep
            # ^ accumulates total distanced traveled for testing abrasion

        # get the downstream link at link:
        downstream_link_at_link = self._fd.link_to_flow_receiving_node[self._fd.downstream_node_at_link()]

        # active parcels on the network:
        in_network = self._parcels.dataset.element_id.values[:, self._time_idx] != _OUT_OF_NETWORK
        active = distance_to_travel_this_timestep>0.0
        active_parcel_ids = np.nonzero(in_network*active)[0] # this line broken.

        # for each parcel.
        for p in active_parcel_ids:

            # Step 1: Move parcel far enough downstream.
            distance_to_exit_current_link = self._grid.at_link["reach_length"][
                int(current_link[p])
            ] * (1 - location_in_link[p])

            # initial distance already within current link
            distance_within_current_link = self._grid.at_link["reach_length"][
                int(current_link[p])
            ] * (location_in_link[p])

            running_travel_distance_in_dt = 0  # initialize to 0
            distance_left_to_travel = distance_to_travel_this_timestep[p]
            while (
                running_travel_distance_in_dt + distance_to_exit_current_link
            ) <= distance_to_travel_this_timestep[p]:
                # distance_left_to_travel > 0:
                # ^ loop through until you find the link the parcel will reside in after moving
                # ... the total travel distance

                # update running travel distance now that you know the parcel will move through the
                # ... current link
                running_travel_distance_in_dt = (
                    running_travel_distance_in_dt + distance_to_exit_current_link
                )

                # now in DS link so this is reset
                distance_within_current_link = 0

                # determine downstream link
                downstream_link_id = downstream_link_at_link[int(current_link[p])]

                # update current link to the next link DS
                current_link[p] = downstream_link_id

                if downstream_link_id == -1:  # parcel has exited the network
                    # (downstream_link_id == -1) and (distance_left_to_travel <= 0):  # parcel has exited the network
                    current_link[p] = _OUT_OF_NETWORK  # overwrite current link
                    break  # break out of while loop

                # ARRIVAL TIME in this link ("current_link") =
                # (running_travel_distance_in_dt[p] / distance_to_travel_this_timestep[p]) * dt + "t" running time
                # ^ DANGER DANGER ... if implemented make sure "t" running time + a fraction of dt
                # ... correctly steps through time.

                distance_to_exit_current_link = self._grid.at_link["reach_length"][
                    int(current_link[p])
                ]

                distance_left_to_travel -= distance_to_exit_current_link

            distance_to_resting_in_link = (
                distance_within_current_link  # zero if parcel in DS link
                + distance_to_travel_this_timestep[p]
                - running_travel_distance_in_dt  # zero if parcel in same link
            )

            # update location in current link
            if current_link[p] == _OUT_OF_NETWORK:
                location_in_link[p] = np.nan

            else:
                location_in_link[p] = (
                    distance_to_resting_in_link
                    / self._grid.at_link["reach_length"][int(current_link[p])]
                )

        # Step 2: Parcel is at rest... Now update its information.

        # reduce D and volume due to abrasion
        vol = _calculate_parcel_volume_post_abrasion(
            self._parcels.dataset.volume[active_parcel_ids, self._time_idx],
            distance_to_travel_this_timestep[active_parcel_ids],
            self._parcels.dataset.abrasion_rate[active_parcel_ids],
        )

        D = _calculate_parcel_grain_diameter_post_abrasion(
            self._parcels.dataset.D[active_parcel_ids, self._time_idx],
            self._parcels.dataset.volume[active_parcel_ids, self._time_idx],
            vol,
        )

        # update parcel attributes

        # arrival time in link
        self._parcels.dataset.time_arrival_in_link[
            active_parcel_ids, self._time_idx
        ] = self._time_idx

        # location in link
        self._parcels.dataset.location_in_link[
            active_parcel_ids, self._time_idx
        ] = location_in_link[active_parcel_ids]

        self._parcels.dataset.element_id[active_parcel_ids, self._time_idx] = current_link[active_parcel_ids]
        #                self._parcels.dataset.active_layer[p, self._time_idx] = 1
        # ^ reset to 1 (active) to be recomputed/determined at next timestep
        self._parcels.dataset.D[active_parcel_ids, self._time_idx] = D
        self._parcels.dataset.volume[active_parcel_ids, self._time_idx] = vol

    def run_one_step(self, dt):
        """Run NetworkSedimentTransporter forward in time.

        When the NetworkSedimentTransporter runs forward in time the following
        steps occur:

            1. A new set of records is created in the Parcels that cooreponds to the new time
            2. If parcels are remain on the network then:
                a. Active parcels are identifed based on entrainment critera.
                b. Effective bed slope is calculated based on inactive parcel volumes
                c. Transport rate is calculated...
                d. Active parcels are moved based on the tranport rate.

        Parameters
        ----------
        dt : float
            Duration of time to run the NetworkSedimentTransporter forward.

        Returns
        -------
        RuntimeError if no parcels remain on the grid.

        """
        self._time += dt

        self._time_idx += 1
        self._create_new_parcel_time()

        if self._this_timesteps_parcels.any():
            self._partition_active_and_storage_layers()
            self._adjust_node_elevation()
            self._update_channel_slopes()
            self._update_transport_time()
            self._move_parcel_downstream(dt)

        else:
            msg = "No more parcels on grid"
            raise RuntimeError(msg)


# %% Methods referenced above, separated for purposes of testing


def _recalculate_channel_slope(z_up, z_down, dx, threshold=1e-4):
    """Recalculate channel slope based on elevation.

    Parameters
    ----------
    z_up : float
        Upstream elevation.
    z_down : float
        Downstream elevation.
    dz : float
        Distance.

    Examples
    --------
    >>> from landlab.components.network_sediment_transporter.network_sediment_transporter import _recalculate_channel_slope
    >>> import pytest
    >>> _recalculate_channel_slope(10., 0., 10.)
    1.0
    >>> _recalculate_channel_slope(0., 0., 10.)
    0.0001
    >>> with pytest.raises(ValueError):
    ...     _recalculate_channel_slope(0., 10., 10.)

    """
    chan_slope = (z_up - z_down) / dx

    if chan_slope < 0.0:
        # chan_slope = 0.0
        # DANGER DANGER ^ that is probably a bad idea.
        raise ValueError("NST Channel Slope Negative")

    if chan_slope < threshold:
        chan_slope = threshold

    return chan_slope


def _calculate_alluvium_depth(
    stored_volume,
    width_of_upstream_links,
    length_of_upstream_links,
    width_of_downstream_link,
    length_of_downstream_link,
    porosity,
):
    """Calculate alluvium depth based on adjacent link inactive parcel volumes.

    Parameters
    ----------
    stored_volume : float
        Total volume of inactive parcels in this link.
    width_of_upstream_links : float
        Channel widths of upstream links.
    length_of_upstream_link : float
        Channel lengths of upstream links.
    width_of_downstream_link : float
        Channel widths of downstream links.
    length_of_downstream_link : float
        Channel lengths of downstream links.
    porosity: float
        Channel bed sediment porosity.

    Examples
    --------
    >>> from landlab.components.network_sediment_transporter.network_sediment_transporter import _calculate_alluvium_depth
    >>> import pytest
    >>> _calculate_alluvium_depth(100,np.array([0.5,1]),np.array([10,10]), 1, 10, 0.2)
    10.0
    >>> _calculate_alluvium_depth(24,np.array([0.1,3]),np.array([10,10]), 1, 1, 0.5)
    3.0
    >>> with pytest.raises(ValueError):
    ...     _calculate_alluvium_depth(24,np.array([0.1,3]),np.array([10,10]), 1, 1, 2)

    """

    alluvium__depth = (
        2
        * stored_volume
        / (
            np.sum(width_of_upstream_links * length_of_upstream_links)
            + width_of_downstream_link * length_of_downstream_link
        )
        / (1 - porosity)
    )
    # NOTE: Jon, porosity was left out in earlier version of the LL component,
    # but it seems it should be in here. Check me: is the eqn correct?

    if alluvium__depth < 0.0:
        raise ValueError("NST Alluvium Depth Negative")

    return alluvium__depth


def _calculate_reference_shear_stress(
    fluid_density, R, g, mean_active_grain_size, frac_sand
):
    """Calculate reference Shields stress (taursg) using the sand content of
    the bed surface, as per Wilcock and Crowe (2003).

    Parameters
    ----------
    fluid_density : float
        Density of fluid (generally, water).
    R: float
        Specific weight..?
    g: float
        Gravitational acceleration.
    mean_active_grain_size: float
        Mean grain size of the 'active' sediment parcels.
    frac_sand: float
        Fraction of the bed surface grain size composed of sand sized parcels.

    Examples
    --------
    >>> from landlab.components.network_sediment_transporter.network_sediment_transporter import (
    ... _calculate_reference_shear_stress)
    >>> from numpy.testing import assert_almost_equal
    >>> assert_almost_equal(
    ...     _calculate_reference_shear_stress(1, 1, 1, 1, 0),
    ...     0.036,
    ...     decimal=2)
    >>> assert_almost_equal(
    ...     _calculate_reference_shear_stress(1000, 1.65, 9.8, 0.1, 0.9),
    ...     33.957,
    ...     decimal=2)

    """

    taursg = (
        fluid_density
        * R
        * g
        * mean_active_grain_size
        * (0.021 + 0.015 * np.exp(-20.0 * frac_sand))
    )

    if np.any(np.asarray(taursg < 0)):
        raise ValueError("NST reference Shields stress is negative")

    return taursg


def _calculate_parcel_volume_post_abrasion(
    starting_volume, travel_distance, abrasion_rate
):
    """Calculate parcel volumes after abrasion, according to Sternberg
    exponential abrasion.

    Parameters
    ----------
    starting_volume : float or array
        Starting volume of each parcel.
    travel_distance: float or array
        Travel distance for each parcel during this timestep, in ___.
    abrasion_rate: float or array
        Mean grain size of the 'active' sediment parcels.

    Examples
    --------
    >>> from landlab.components.network_sediment_transporter.network_sediment_transporter import _calculate_parcel_volume_post_abrasion
    >>> import pytest
    >>> _calculate_parcel_volume_post_abrasion(10,100,0.003)
    7.4081822068171785
    >>> _calculate_parcel_volume_post_abrasion(10,300,0.1)
    9.3576229688401746e-13
    >>> with pytest.raises(ValueError):
    ...     _calculate_parcel_volume_post_abrasion(10,300,-3)

    """

    volume = starting_volume * np.exp(travel_distance * (-abrasion_rate))

    if np.any(volume > starting_volume):
        raise ValueError("NST parcel volume *increases* due to abrasion")

    return volume


def _calculate_parcel_grain_diameter_post_abrasion(
    starting_diameter, pre_abrasion_volume, post_abrasion_volume
):
    """Calculate parcel grain diameters after abrasion, according to Sternberg
    exponential abrasion.

    Parameters
    ----------
    starting_diameter : float or array
        Starting volume of each parcel.
    pre_abrasion_volume: float or array
        Parcel volume before abrasion.
    post_abrasion_volume: float or array
        Parcel volume after abrasion.

    Examples
    --------
    >>> from landlab.components.network_sediment_transporter.network_sediment_transporter import _calculate_parcel_grain_diameter_post_abrasion
    >>> import numpy as np
    >>> from numpy.testing import assert_almost_equal

    If no abrasion happens, we should get the same value.

    >>> _calculate_parcel_grain_diameter_post_abrasion(10, 1, 1)
    10.0

    If some abrasion happens, test the value.

    >>> starting_diameter = 10
    >>> pre_abrasion_volume = 2
    >>> post_abrasion_volume = 1
    >>> expected_value = (
    ...     starting_diameter *
    ...     ( post_abrasion_volume / pre_abrasion_volume) ** (1. / 3.))
    >>> print(np.round(expected_value, decimals=3))
    7.937
    >>> assert_almost_equal(
    ...    _calculate_parcel_grain_diameter_post_abrasion(10, 2, 1),
    ...    expected_value)

    """

    abraded_grain_diameter = starting_diameter * (
        post_abrasion_volume / pre_abrasion_volume
    ) ** (1.0 / 3.0)

    return abraded_grain_diameter

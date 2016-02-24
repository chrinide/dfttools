"""
This submodule contains key types for handling coordinate-dependent data:
``UnitCell`` and ``Grid``.
"""
import math
import itertools
from functools import wraps
import warnings

import numpy
from numpy import random
from scipy import linalg
import numericalunits

from .blochl import tetrahedron, tetrahedron_plain
from .gf import greens_function

def input_as_list(func):
    
    @wraps(func)
    def a_w(*args, **kwargs):
        self = args[0]
        if len(args) > 2:
            args = [self, list(args[1:])]
        elif len(args) == 2:
            try:
                iter(args[1])
            except TypeError:
                args = [self, list(args[1:])]
        else:
            args = [self, []]
            
        return func(*args, **kwargs)
            
    return a_w

def __angle__(v1,v2, axis = -1):
    """
    Calculates angles between sets of vectors.
    
    Args:
    
        v1,v2 (array): arrays of the same size with vectors'
        coordinates.
        
    Kwargs:
    
        axis (int): dimension to sum over.
        
    Returns:
    
        A numpy array containing cosines between the vectors.
    """
    return (v1*v2).sum(axis=axis)/((v1**2).sum(axis=axis)*(v2**2).sum(axis=axis))**.5
    
def __xyz2i__(i):
    try:
        return {'x':0, 'y':1, 'z':2}[i]
    except KeyError:
        return i
        
class ArgumentError(Exception):
    pass
    
class Basis(object):
    
    """
    A class describing a set of vectors representing a basis.
    
    Args:
    
        vectors (array): a 2D or a 1D array of floats representing
        vectors of the basis set.
        
    Kwargs:
    
        kind (str): a shortcut keyword for several most common basis
        sets:
        
        * 'default': expects ``vectors`` to be a 2D array with basis
          vectors in cartesian coordinates;
        * 'orthorombic': expects ``vectors`` to be a 1D array with
          dimensions of an orthorombic basis set;
        * 'triclinic': expects ``vectors`` to be a 1D array with 3
          lengths of edges and 3 cosines of face angles.
        
        meta (dict): a metadata for this Basis.
    """
    
    def __init__(self, vectors, kind = 'default', meta = None):
        
        vectors = numpy.array(vectors, dtype = numpy.float64)
        
        if kind == 'default':
            self.vectors = vectors
            
        elif kind == 'orthorombic':
            self.vectors = numpy.diag(vectors)
            
        elif kind == 'triclinic':
            lengths = vectors[0:3]
            cosines = vectors[3:]
            volume = lengths[0]*lengths[1]*lengths[2]*(
                1+\
                2*cosines[0]*cosines[1]*cosines[2]-\
                cosines[0]**2-cosines[1]**2-cosines[2]**2
            )**.5
            sines = (1-cosines**2)**.5
            height = volume/lengths[0]/lengths[1]/sines[2]
            self.vectors = numpy.array((
                (lengths[0], 0, 0),
                (lengths[1]*cosines[2], lengths[1]*sines[2], 0),
                (lengths[2]*cosines[1], abs((lengths[2]*sines[1])**2 - height**2)**.5, height)
            ), dtype = numpy.float64)
            
        else:
            raise ArgumentError("Unknown kind='{}'".format(kind))

        if not meta is None:
            self.meta = meta.copy()
        else:
            self.meta = {}
            
        self.units = {}

    def __export_units__(self, attr):
        x = getattr(self, attr)
        if not attr in self.units:
            return x
        measure = getattr(numericalunits, self.units[attr]) 
        return x/measure

    def __import_units__(self, attr):
        x = getattr(self, attr)
        if attr in self.units:
            measure = getattr(numericalunits, self.units[attr]) 
            setattr(self, attr, x*measure)
        
    def __getstate__(self):
        return {
            "vectors":self.__export_units__("vectors"),
            "meta":self.meta,
            "units":self.units,
        }
        
    def __setstate__(self,data):
        self.__init__(
            data["vectors"],
            meta = data["meta"],
        )
        self.units = data["units"]
        self.__import_units__("vectors")
        
    def __eq__(self, another):
        return type(another) == type(self) and numpy.all(self.vectors == another.vectors)
        
    def transform_to(self, basis, coordinates):
        """
        Transforms coordinates to another basis set.
        
        Args:
        
            basis (Basis): a new basis to transform to.
            
            coordinates (array): an array of coordinates to be
            transformed.
            
        Returns:
        
            An array with transformed coordinates.
        """
        coordinates = numpy.array(coordinates, dtype = numpy.float64)
        return numpy.tensordot(
            coordinates,
            numpy.tensordot(
                self.vectors,
                numpy.linalg.inv(basis.vectors),
                axes=((1,),(0,))
            ),
            axes=((len(coordinates.shape)-1,),(0,))
        )
        
    def transform_from(self, basis, coordinates):
        """
        Transforms coordinates from another basis set.
        
        Args:
        
            basis (Basis): a basis to transform from.
            
            coordinates (array): an array of coordinates to be
            transformed.
            
        Returns:
        
            An array with transformed coordinates.
        """
        return basis.transform_to(self, coordinates)
        
    def transform_to_cartesian(self, coordinates):
        """
        Transforms coordinates to cartesian.
        
        Args:
            
            coordinates (array): an array of coordinates to be
            transformed.
            
        Returns:
        
            An array with transformed coordinates.
        """
        return self.transform_to(
            Basis(numpy.eye(self.vectors.shape[0])),
            coordinates,
        )
        
    def transform_from_cartesian(self, coordinates):
        """
        Transforms coordinates from cartesian.
        
        Args:
            
            coordinates (array): an array of coordinates to be
            transformed.
            
        Returns:
        
            An array with transformed coordinates.
        """
        return self.transform_from(
            Basis(numpy.eye(self.vectors.shape[0])),
            coordinates,
        )
    
    def volume(self):
        """
        Computes the volume of a triclinic cell represented by the basis.
        
        Returns:
        
            Volume of the cell in **m^3**.
        """
        return abs(numpy.linalg.det(self.vectors))
        
    def reciprocal(self):
        """
        Computes a reciprocal basis.
        
        Returns:
        
            A reciprocal basis.
            
        .. note::
        
            The :math:`2 \pi` multiplier is not present.
        
        """
        return Basis(numpy.swapaxes(numpy.linalg.inv(self.vectors),0,1))
        
    def vertices(self):
        """
        Computes cartesian coordinates of all vertices of the basis cell.
        
        Returns:
        
            Cartesian coordinates of all vertices.
        """
        result = []
        for v in itertools.product((0.0,1.0), repeat = self.vectors.shape[0]):
            result.append(self.transform_to_cartesian(numpy.array(v)))
        return numpy.array(result)
        
    def edges(self):
        """
        Computes pairs of cartesian coordinates of all edges of the
        basis cell.
        
        Returns:
        
            A list of pairs with cartesian coordinates of vertices
            forming edges.
        """
        result = []
        for e in range(self.vectors.shape[0]):
            for v in itertools.product((0.0,1.0), repeat = self.vectors.shape[0]-1):
                v1 = v[:e] + (0.,) + v[e:]
                v2 = v[:e] + (1.,) + v[e:]
                result.append((
                    (self.vectors*numpy.array(v1)[:,numpy.newaxis]).sum(axis = 0),
                    (self.vectors*numpy.array(v2)[:,numpy.newaxis]).sum(axis = 0),
                ))
        return numpy.array(result)
        
    def faces(self):
        """
        Computes faces and returns corresponding cartesian coordinates.
        
        Returns:
        
            A list of lists of coordinates defining face polygon coordinates.
        """
        raise NotImplementedError
        
    def copy(self):
        """
        Calculates a copy.
        
        Returns:
        
            A deep copy of self.
        """
        return Basis(self.vectors, meta = self.meta)
    
    @input_as_list
    def stack(self, basises, vector = 'x', tolerance = 1e-10):
        """
        Stacks several basises along one of the vectors.
        
        Args:
        
            basises (list): basises to stack. Corresponding
            vectors of all basises being stacked should match.
            
        Kwargs:
        
            vector (str,int): a vector along which to stack, either 'x',
            'y', 'z' or an int specifying the vector.
        
            tolerance (float): a largest possible error in input basises'
            vectors
            
        Raises:
        
            ArgumentError: in the case of vector mismatch.
            
        Returns:
        
            A larger basis containing all argument cell stacked.
        """
        basises = [self]+basises
        d = __xyz2i__(vector)
            
        otherVectors = list(range(basises[0].vectors.shape[0]))
        del otherVectors[d]
        
        # 3d array with lattice vectors: shapes[i,j,k] i=cell, j=lattice vector, k = component
        shapes = numpy.concatenate( tuple(
            i.vectors[numpy.newaxis,...] for i in basises
        ), axis = 0)
        
        # check the stacking vectors of each cell pointing the same direction
        # and if the rest of lattice vectors coincide
        stackingVectorsSum = shapes[:,d,:].sum(axis = 0)
        vecLengths = (shapes**2).sum(axis = 2)**0.5
        otherVectors_d = shapes[:,otherVectors,:] - shapes[0,otherVectors,:][numpy.newaxis,...]
        otherVectors_ds = (otherVectors_d**2).sum(axis = -1)**.5
        
        if numpy.any( otherVectors_ds > tolerance * vecLengths[:,otherVectors] ) \
            or numpy.any(numpy.abs(__angle__(shapes[:,d,:],stackingVectorsSum[numpy.newaxis,:])-1) > tolerance):
                raise ArgumentError('Dimension mismatch for stacking:\n{}\nCheck your input basis vectors or set tolerance to at least {} to skip this error'.format(
                    shapes,
                    max(
                        numpy.amax(otherVectors_ds/vecLengths[:,otherVectors]),
                        numpy.amax(numpy.abs(__angle__(shapes[:,d,:],stackingVectorsSum[numpy.newaxis,:])-1))
                    ),
                ))
            
        shape = self.vectors.copy()
        shape[d,:] = stackingVectorsSum
            
        return Basis(shape, meta = self.meta)

    @input_as_list
    def repeated(self, times):
        """
        Produces a new basis from a given by repeating it in all
        directions.
        
        Args:
        
            times (array): array of ints specifying how much the basis
            should be repeated along each of the vectors.
        """
        c = self
        for i, t in enumerate(times):
            if not isinstance(t, int):
                raise ValueError("The input [{:d}] should be integers, found {} instead".format(i,times))
            c = c.stack(*((c,)*(t-1)), vector = i)
            
        return c

    @input_as_list
    def reorder_vectors(self, new):
        """
        Reorders vectors.
        
        Args:
        
            new (array): new mapping of vectors.
            
        Example:
        
            >>> basis.reorder_vectors(0, 1, 2) # does nothing
            >>> basis.reorder_vectors(1, 0, 2) # swaps first and second vectors.
        """
        new = tuple(__xyz2i__(i) for i in new)
        
        if not len(new) == self.vectors.shape[0]:
            raise ArgumentError("The new mapping of vectors should be of the size of {:d}".format(self.vectors.shape[0]))
            
        if not len(set(new)) == self.vectors.shape[0]:
            raise ArgumentError("The input contains duplicates")
            
        self.vectors = self.vectors[new,:]
    
    @input_as_list
    def generate_path(self, points, n = 100, force_edges = False):
        """
        Generates a path in this basis.
        
        Args:
        
            points (array): edges of the path where the leading dimension
            corresponds to points and the second dimension corresponds
            to the coordinates of the points in this basis.
            
        Kwargs:
        
            n (int): number of points;
            
            force_edges (int): force to include the edges into the final
            list of coordinates.
            
        Returns:
        
            A 2D array with the path. The coordinates of points are
            given in this basis.
        """
        points = numpy.array(points)
        
        cartesian = self.transform_to_cartesian(points)
        lengths = ((cartesian[1:,:]-cartesian[:-1,:])**2).sum(axis = -1)**.5
        lengths = numpy.concatenate(((0,),lengths,))
        lengths = numpy.cumsum(lengths)
        
        if not force_edges:
            
            uniform = numpy.linspace(0,lengths[-1],n)
            large = numpy.searchsorted(lengths,uniform)
            large[0] = 1
            small = ((uniform - lengths[large-1]) / (lengths[large] - lengths[large-1]))[:,numpy.newaxis]
            return points[large-1,:] * (1 - small) + points[large,:] * small
            
        else:
            
            raise NotImplementedError

class UnitCell(Basis):
    """
    A class describing a crystal unit cell in a periodic environment.
    
    Args:
    
        basis (Basis): a crystal basis.
        
        coordinates (array): a 2D array of coordinates of atoms (or any
        other instances)
        
        values (array): an array of atoms (or any other instances) with
        the leading dimenstion being the same as the one of
        ``coordinates`` array.

    Kwargs:
    
        c_basis (str,Basis): a Basis for input coordinates or 'cartesian'
        if coordinates are passed in the cartesian basis.
    """

    def __init__(self, basis, coordinates, values, c_basis = None):
        
        Basis.__init__(self, basis.vectors, meta = basis.meta)
        
        dims = self.vectors.shape[0]
        
        # Process coordinates and vectors input
        self.coordinates = numpy.array(coordinates, dtype = numpy.float64)
        
        if len(self.coordinates.shape) == 1:
            if not self.coordinates.shape == (dims,):
                raise ArgumentError('Coordinates array is 1D, {:d} coordinates have to be specified instead of {:d}'.format(dims,self.coordinates.shape[0]))
                
            self.coordinates = self.coordinates[numpy.newaxis,...]
                
        elif len(self.coordinates.shape) == 2:
            if self.coordinates.shape[1] != dims:
                raise ArgumentError('Coordinates array is 2D but the last dimension {:d} is not equal to space dimensionality {:d}'.format(self.coordinates.shape[1], dims))
        
        # Coordinates are now prepeared, proceed to values
        self.values = numpy.array(values)
        if len(self.values.shape) == 0:
            self.values = self.values[numpy.newaxis,...]
                
        if self.values.shape[0] < self.coordinates.shape[0] and self.coordinates.shape[0] % self.values.shape[0] == 0:
            # Broadcast values repeatedly
            self.values = numpy.array( tuple(
                self.values[i%self.values.shape[0]] for i in range(self.coordinates.shape[0])
            ) )
            
        elif not self.values.shape[0] == self.coordinates.shape[0]:
            raise ArgumentError('Mismatch of sizes of coordinates and values arrays: {:d} vs {:d}'.format(
                self.coordinates.shape[0],
                self.values.shape[0]
            ))
            
        # Process basis information
        if c_basis == None:
            pass
            
        elif c_basis == 'cartesian':
            self.coordinates = self.transform_from_cartesian(self.coordinates)
            
        else:
            self.coordinates = self.transform_from(c_basis, self.coordinates)
        
    def __getstate__(self):
        return {
            "vectors":self.vectors,
            "coordinates":self.coordinates,
            "values":self.values,
            "meta":self.meta,
        }
        
    def __setstate__(self,data):
        self.vectors = data["vectors"]
        self.meta = data["meta"]
        self.coordinates = data["coordinates"]
        self.values = data["values"]
    
    def __eq__(self, another):
        return Basis.__eq__(self,another) and numpy.all(self.coordinates == another.coordinates) and numpy.all(self.values == another.values)
        
    @input_as_list
    def angles(self, ids):
        """
        Computes angles between cell specimens.
        
        Args:
        
            ids (array): a set of specimen IDs to compute angles between.
            Several shapes are accepted:
            
            * nx3 array: computes n cosines of angles [n,0]-[n,1]-[n,2];
            * 1D array of length n: computes n-2 cosines of angles
              [n-1]-[n]-[n+1];
            
        Returns:
        
            A numpy array containing cosines of angles specified.
            
        Example:
        
            Following are the valid calls:
            
            >>> cell.angles((0,1,2)) # angle between vectors connecting {second and first} and {second and third} species
            >>> cell.angles(0,1,2) # a simplified version of above
            >>> cell.angles(0,1,3,2) # two angles along path: 0-1-3 and 1-3-2
            >>> cell.angles(tuple(0,1,3,2)) # same as above
            >>> cell.angles((0,1,3),(1,3,2)) # same as above
        """
        
        v = self.cartesian()        
        ids = numpy.array(ids, dtype = numpy.int64)
        
        if len(ids.shape)==1:
            if ids.shape[0]<3:
                raise ArgumentError("Only %i points are found, at least 3 required" % ids.shape[0])
            vectors = v[ids[:-1],:]-v[ids[1:],:]
            nonzero = numpy.argwhere((vectors**2).sum(axis=1) > 0)[:,0]
            if nonzero.shape[0] == 0:
                raise ArgumentError("All points coincide")

            vectors[:nonzero[0]] = vectors[nonzero[0]]
            vectors[nonzero[-1]+1:] = vectors[nonzero[-1]]
            
            vectors_1 = vectors[:-1]
            vectors_2 = -vectors[1:]
            
            for i in range(nonzero.shape[0]-1):
                vectors_1[nonzero[i]+1:nonzero[i+1]] = vectors_1[nonzero[i]]
                vectors_2[nonzero[i]:nonzero[i+1]-1] = vectors_2[nonzero[i+1]-1]
            
        elif len(ids.shape)==2:
            if ids.shape[1]!=3:
                raise ArgumentError("The input array is [%ix%i], required [nx3]" % ids.shape)
            vectors_1 = v[ids[:,0],:] - v[ids[:,1],:]
            vectors_2 = v[ids[:,2],:] - v[ids[:,1],:]
        else:
            raise ArgumentError("The input array has unsupported dimensionality %i" % len(ids.shape))
        
        return __angle__(vectors_1,vectors_2)
        
    @input_as_list
    def distances(self, ids):
        """
        Computes distances between species and specified points.
        
        Args:
        
            ids (array): a list of specimen IDs to compute distances
            between. Several shapes are accepted:
            
            * empty: returns a 2D matrix of all possible distances
            * nx2 array of ints: returns n distances between each pair
              of [n,0]-[n,1] species;
            * 1D array of ints of length n: returns n-1 distances
              between each pair of [n-1]-[n] species;
        
        Returns:
        
            A numpy array containing list of distances.
        """
        
        v = self.cartesian()
        
        if len(ids) == 0:
            return ((v[numpy.newaxis,...] - v[:,numpy.newaxis,:])**2).sum(axis = -1)**.5
            
        ids = numpy.array(ids, dtype = numpy.int64)
                
        if len(ids.shape) == 1:
            if ids.shape[0] < 2:
                raise ArgumentError("Only %i points are found, at least 2 required" % ids.shape[0])
            return ((v[ids[:-1],:]-v[ids[1:],:])**2).sum(axis = 1)**.5
            
        elif len(ids.shape) == 2:
            if ids.shape[1] != 2:
                raise ArgumentError("The input array is [%ix%i], required [nx2]" % ids.shape)
            return ((v[ids[:,0],:]-v[ids[:,1],:])**2).sum(axis = 1)**.5
            
        else:
            raise ArgumentError("The input array has unsupported dimensionality %i" % len(ids.shape))
        
    def size(self):
        """
        Retrieves the number of points or species in this unit cell.
        
        Returns:
        
            Number of points or species in cell.
        """
        return self.coordinates.shape[0]
        
    def cartesian(self):
        """
        Computes cartesian coordinates.
        
        Returns:
        
            A numpy array with cartesian coordinates
        """
        return self.transform_to_cartesian(self.coordinates)
    
    def copy(self):
        """
        Calculates a copy.
        
        Returns:
        
            A copy of self.
        """
        return UnitCell(
            Basis(
                self.vectors,
                meta = self.meta
            ),
            self.coordinates,
            self.values)
        
    def normalized(self, sort = None):
        """
        Moves all species respecting periodicity so that each
        coordinate becomes in the unit range 0<=x<1 in the cell basis.
        Sorts the data if ``sort`` provided.
        
        Kwargs:
        
            sort: either 'x', 'y', 'z' or a consequetive number of a
            vector to sort coordinates along.
        
        Returns:
        
            A new grid with normalized data.
        """
        sort = __xyz2i__(sort)
        
        result = self.copy()
        result.coordinates = result.coordinates % 1
        if not sort is None:
            result.apply(numpy.argsort(result.coordinates[:,sort]))
            
        return result
        
    def packed(self):
        """
        Moves all species as close to the origin as it is possible. Does
        not perform translation.
        
        Returns:
        
            A new unit cell with packed coordinates.
        """
        result = self.normalized()
        coordinates = result.cartesian()
        vertices = result.vertices()
        
        d = coordinates[:,numpy.newaxis,:] - vertices[numpy.newaxis, :, :]
        d = (d**2).sum(axis = -1)
        d = numpy.argmin(d, axis = -1)
        
        coordinates -= vertices[d,:]
        
        result.coordinates = result.transform_from(
            Basis(
                numpy.eye(result.vectors.shape[0])
            ),
            coordinates)
            
        return result
    
    @input_as_list
    def isolated(self, gaps, units = "crystal"):
        """
        Generates an isolated representation of this cell.
        
        Symmetrically adds vacuum along all unit cell vectors such that
        resulting unit cell vectors are parallel to the initial ones.
        
        Args:
        
            gaps (array): size of the vacuum layer in each direction
            either in cartesian or in crystal units.
            
        Kwargs:
        
            units (str): units of the vacuum size, 'cartesian' or
            'crystal'
            
        Returns:
        
            A new unit cell with spacially isolated species.
        """
        gaps = numpy.array(gaps, dtype = numpy.float64)
        if units == "cartesian":
            gaps /= ((self.vectors**2).sum(axis = 1)**.5)
        elif units == "crystal":
            pass
        else:
            raise ArgumentError("Unknown units: '{}'".format(str(units)))
        
        result = self.copy()
        
        gaps += 1
        result.vectors *= gaps[...,numpy.newaxis]
        result.coordinates /= gaps[numpy.newaxis,...]
        result.coordinates += (0.5*(gaps-1)/gaps)[numpy.newaxis,...]
        
        return result
            
    def isolated2(self, gap):
        """
        Generates an isolated representation of this cell.
        
        The resulting cell is rectangular and contains space gaps of at
        least "gap" size.
        
        Args:
        
            gap (float): size of the space gap along all ``self.vectors``.
            
        Returns:
        
            A new unit cell with spacially isolated species.
        """
        c = self.normalized()
        coordinates = c.cartesian()+gap
        shape = numpy.amax(c.vertices(), axis = 0)+2*gap
        return UnitCell(
            Basis(
                shape,
                kind = 'orthorombic',
                meta = self.meta,
            ),
            coordinates,
            self.values,
            c_basis = 'cartesian')
            
    @input_as_list
    def select(self, piece):
        """
        Selects a piece of this cell.
        
        Args:
        
            piece (array): fraction of the cell to be selected, see
            examples. The order of coordinates in ``piece`` is ``x_from, y_from, ..., z_from, x_to, y_to, ..., z_to``.
            
        Returns:
        
            A numpy array with bools defining whether particular specimen
            is selected or not.
            
        Example:
            
            >>> cell.select((0,0,0,1,1,1)) # select all species with coordinates within (0,1) range
            >>> cell.select(0,0,0,1,1,1) # a simplified version of above
            >>> cell.select(0,0,0,0.5,1,1) # select the 'left' part
            >>> cell.select(0.5,0,0,1,1,1) # select the 'right' part
        """
        if not len(piece) == 2*self.vectors.shape[0]:
            raise ArgumentError("Wrong coordinates array: expecting {:d} elements, found {:d}".format(
                2*self.vectors.shape[0], len(piece)
            ))
            
        piece = numpy.reshape(piece,(2,-1))
        p1 = numpy.amin(piece,axis = 0)
        p2 = numpy.amax(piece,axis = 0)
        return numpy.all(self.coordinates< p2[numpy.newaxis,:],axis = 1) &\
               numpy.all(self.coordinates>=p1[numpy.newaxis,:],axis = 1)
        
    @input_as_list
    def apply(self, selection):
        """
        Applies selection to this cell.
        
        Inverse of ``UnitCell.discard``.
        
        Args:
        
            selection (array): seleted species.
            
        Example:
        
            >>> selection = cell.select((0,0,0,0.5,1,1)) # Selects species in the 'left' part of the unit cell.
            >>> cell.apply(selection) # Applies selection. Species outside the 'left' part are discarded.
        """
        selection = numpy.array(selection)
        self.coordinates = self.coordinates[selection,:]
        self.values = self.values[selection]

    @input_as_list
    def discard(self, selection):
        """
        Removes specified species from cell.
        
        Inverse of ``Cell.apply``.
        
        Args:
        
            selection (array): species to remove.
            
        Example:
        
            >>> selection = cell.select((0,0,0,0.5,1,1)) # Selects species in the 'left' part of the unit cell.
            >>> cell.discard(selection) # Discards selection. Species inside the 'left' part are removed.
        """
        self.apply(~numpy.array(selection))

    @input_as_list
    def cut(self, piece):
        """
        Selects a piece of this unit cell and returns it as a smaller
        unit cell.
        
        Kwargs:
        
            piece (array): fraction of the cell to be selected. The order
            of coordinates in ``piece`` is ``x_from, y_from, ..., z_from, x_to, y_to, ..., z_to``.
            
        Returns:
        
            A smaller unit cell selected.
        """
        result = self.copy()
        result.apply(result.select(piece))
        
        piece = numpy.reshape(piece,(2,-1))
        p1 = numpy.amin(piece,axis = 0)
        p2 = numpy.amax(piece,axis = 0)
        
        result.coordinates -= p1[numpy.newaxis,:]
        result.coordinates /= (p2-p1)[numpy.newaxis,:]
        result.vectors *= (p2-p1)[numpy.newaxis,:]
        return result

    @input_as_list
    def add(self, cells):
        """
        Adds species from another unit cells to this one.
        
        Args:
        
            cells (arguments): unit cells to be merged with.
            
        Returns:
        
            A new unit cell with merged data.
        """
        c = [self.coordinates]
        v = [self.values]
        
        for cell in cells:
            if not numpy.all(cell.vectors == self.vectors):
                raise ArgumentError('Dimension mismatch: %r, %r' % (self.vectors, cell.vectors))
            c.append(cell.coordinates)
            v.append(cell.values)
        
        return UnitCell(
            Basis(
                self.vectors,
                meta = self.meta,
            ),
            numpy.concatenate(c, axis = 0),
            numpy.concatenate(v, axis = 0))
    
    @input_as_list
    def stack(self, cells, vector = 'x', tolerance = 1e-10):
        """
        Stacks several cells along one of the vectors.
        
        Args:
        
            cells (list): cells to stack. Corresponding vectors of
            all cells being stacked should match.
            
        Kwargs:
        
            vector (str,int): a vector along which to stack, either 'x',
            'y', 'z' or an int specifying the vector.
        
            tolerance (float): a largest possible error in input cells'
            vectors
            
        Raises:
        
            ArgumentError: in the case of vector mismatch.
            
        Returns:
        
            A bigger unit cell containing all argument cell stacked.
        """
        cells = [self]+cells
        d = __xyz2i__(vector)
        dims = self.vectors.shape[0]
        
        for c in cells:
            if not type(c) in (UnitCell, Basis):
                raise ArgumentError('Cannot stack object {}'.format(c))
            
        basis = Basis.stack(*cells, vector = vector, tolerance = tolerance)
         
        values = numpy.concatenate(tuple(cell.values for cell in cells if isinstance(cell, UnitCell)), axis = 0)
            
        stackingVectorsLen = numpy.array(tuple((cell.vectors[d,:]**2).sum()**.5 for cell in cells))
        shifts = numpy.cumsum(stackingVectorsLen)
        shifts = shifts/shifts[-1]
        
        # kx+b
        k = numpy.ones((len(cells),dims))
        k[:,d] = stackingVectorsLen/stackingVectorsLen.sum()
        b = numpy.zeros((len(cells),dims))
        b[:,d] = numpy.concatenate(((0,),shifts[:-1]))
        
        coordinates = numpy.concatenate(tuple(
            cell.coordinates*k[numpy.newaxis,i,:]+b[numpy.newaxis,i,:] for i,cell in enumerate(cells) if isinstance(cell, UnitCell) 
        ),axis = 0)
            
        return UnitCell(basis, coordinates, values)

    @input_as_list
    def supercell(self, vec):
        """
        Produces a supercell from a given unit cell.
        
        Args:
        
            vec (array): the supercell vectors in units of current unit
            cell vectors
            
        Returns:
        
            A new supercell.
        """
        vec = numpy.array(vec, dtype = numpy.float64)
        
        sc_min = None
        sc_max = None
        
        for v in itertools.product((0.0,1.0), repeat = vec.shape[0]):
            
            vertex = (vec*numpy.array(v)[:,numpy.newaxis]).sum(axis = 0)
            
            if sc_min is None:
                sc_min = numpy.array(v)
            else:
                sc_min = numpy.minimum(sc_min, vertex)
                
            if sc_max is None:
                sc_max = numpy.array(v)
            else:
                sc_max = numpy.maximum(sc_max, vertex)
        
        # Fix roundoff
        random_displacement = random.rand(self.coordinates.shape[-1])[numpy.newaxis,:]
        u = self.copy()
        u.coordinates += random_displacement
        
        sc = u.repeated((sc_max - sc_min).astype(numpy.int64)).normalized()
        
        origin = (self.vectors * sc_min[:,numpy.newaxis]).sum(axis = 0)
        
        result = UnitCell(
            Basis(
                numpy.dot(vec, self.vectors),
                meta = self.meta),
            sc.cartesian() + origin[numpy.newaxis,:],
            sc.values,
            c_basis = 'cartesian',
        )
        
        result.apply(numpy.all(numpy.logical_and(result.coordinates >= 0, result.coordinates < 1), axis = 1))
        result.coordinates -= result.transform_from(u, random_displacement)
        return result.normalized()
    
    def species(self):
        """
        Collects number of species of each kind in this cell.
        
        Particularly useful for counting the number of atoms.
        
        Returns:
        
            A dictionary containing species as keys and number of atoms
            as values.
        """
        answer = {}
        for s in self.values:
            try:
                answer[s] += 1
            except:
                answer[s] = 1
        return answer

    @input_as_list
    def reorder_vectors(self, new):
        """
        Reorders vectors.
        
        Args:
        
            new (array): new mapping of vectors.
            
        Example:
        
            >>> cell.reorder_vectors(0, 1, 2) # does nothing
            >>> cell.reorder_vectors(1, 0, 2) # swaps first and second vectors.
            
        .. note::
        
            A call to this method does not modify the output of ``self.cartesian()``.
        """
        new = tuple(__xyz2i__(i) for i in new)
        Basis.reorder_vectors(self, new)
        self.coordinates = self.coordinates[:, new]
        
    def as_grid(self, fill = float("nan")):
        """
        Converts this unit cell to grid.
        
        Kwargs:
        
            fill: default value to fill with
        
        Returns:
        
            A new grid with data from initial cell.
        """
        
        # Convert coordinates
        coordinates = list(
            numpy.sort(
                numpy.unique(self.coordinates[:,i])
            ) for i in range(self.coordinates.shape[1])
        )
        
        # A coordinates lookup table
        coord2index = list(
            dict(zip(a, range(a.size))) for a in coordinates
        )
        
        # Convert values
        data = fill*numpy.ones(tuple( a.size for a in coordinates) + self.values.shape[1:])
        
        for c,v in zip(self.coordinates, self.values):
            indexes = tuple( coord2index[i][cc] for i, cc in enumerate(c))
            data[indexes] = v
            
        return Grid(
            Basis(self.vectors, meta = self.meta),
            coordinates,
            data,
        )
        
    @input_as_list
    def interpolate(self, points, driver = None, periodic = True, **kwargs):
        """
        Interpolates values at specified points. By default uses
        ``scipy.interpolate.griddata``.
        
        Args:
        
            points (array): points to interpolate at.
            
        Kwargs:
        
            driver (func): interpolation driver.
            
            periodic (bool): employs periodicity of a unit cell.
            
            kwargs: keywords to the driver.
            
        Returns:
        
            A new unit cell with interpolated data.
            
        """
        points = numpy.array(points, dtype = numpy.float64)
        
        if driver is None:
            from scipy import interpolate
            driver = interpolate.griddata
        
        if periodic:
            
            # Avoid edge problems by creating copies of this cell
            supercell = self.repeated((3,)*self.vectors.shape[0]).normalized()
            
            data_points = supercell.cartesian()
            data_values = supercell.values
            
            # Shift points to the central unit cell
            points_i = self.transform_to_cartesian(points % 1) + self.vectors.sum(axis = 0)[numpy.newaxis, :]
            
        else:
            
            data_points = self.cartesian()
            data_values = self.values
            points_i = self.transform_to_cartesian(points)
        
        # Interpolate
        return UnitCell(
            Basis(self.vectors, meta = self.meta),
            points,
            driver(data_points, data_values, points_i, **kwargs),
        )

class Grid(Basis):
    """
    A class describing a data on a grid in a periodic environment.
    
    Args:
    
        basis (Basis): a crystal basis.
        
        coordinates (array): a list of arrays of coordinates specifying
        grid.
        
        values (array): a multidimensional array with data on the grid.
    """

    def __init__(self, basis, coordinates, values):
        
        Basis.__init__(self, basis.vectors, meta = basis.meta)
        dims = self.vectors.shape[0]
        self.coordinates = list(numpy.array(c, dtype = numpy.float64) for c in coordinates)
        self.values = numpy.array(values)

        # Proceed to checks
        if not len(self.coordinates) == dims:
            raise ArgumentError("The size of the basis is {:d} but the number of coordinates specified is different: {:d}".format(dims, len(self.coordinates)))
            
        for i, c in enumerate(self.coordinates):
            if not len(c.shape) == 1:
                raise ArgumentError("Coordinates[{:d}] is not a 1D array".format(i))
        
        if len(self.values.shape) < dims:
            raise ArgumentError("The dimensionality of a 'values' array is less ({:d}) than expected ({:d})".format(len(self.values.shape),dims))
            
        for i in range(dims):
            if not self.values.shape[i] == self.coordinates[i].shape[0]:
                raise ArgumentError("The {:d} dimension of 'values' array is equal to {:d} which is different from the size of a corresponding 'coordinates' array {:d}".format(i,self.values.shape[i],self.coordinates[i].shape[0]))
        
    def __getstate__(self):
        return {
            "vectors":self.vectors,
            "coordinates":self.coordinates,
            "values":self.values,
            "meta":self.meta,
        }
        
    def __setstate__(self,data):
        self.__init__(
            Basis(
                data["vectors"],
                meta = data["meta"],
            ),
            data["coordinates"],
            data["values"],
        )
        
    def __eq__(self, another):
        result = Basis.__eq__(self,another)
        result = result and numpy.all(self.values == another.values)
        for i,j in zip(self.coordinates, another.coordinates):
            result = result and numpy.all(i==j)
        return result
        
    def size(self):
        """
        Retrieves the total size of points on the grid.
        
        Returns:
        
            Number of species in cell as an integer.
        """
        r = 1
        for a in self.coordinates:
            r *= a.size
        return r
    
    def explicit_coordinates(self):
        """
        Creates an (N+1)D array with explicit coordinates at each grid
        point.
        
        Returns:
        
            An (N+1)D array with coordinates.
        """
        mg = numpy.meshgrid(*self.coordinates, indexing='ij')
        return numpy.concatenate(tuple(i[...,numpy.newaxis] for i in mg), axis = len(mg))
        
    def cartesian(self):
        """
        Computes cartesian coordinates.
        
        Returns:
        
            A multidimensional numpy array with cartesian coordinates at
            each grid point.
        """
        return self.transform_to_cartesian(self.explicit_coordinates())
        
    def copy(self):
        """
        Calculates a copy.
        
        Returns:
        
            A copy of self.
        """
        return Grid(
            Basis(
                self.vectors,
                meta = self.meta
            ),
            self.coordinates,
            self.values)
        
    def normalized(self):
        """
        Moves all grid points respecting periodicity so that each
        coordinate becomes in the unit range 0<=x<1 in the cell basis.
        Sorts the data.
        
        Returns:
        
            A new grid with normalized data.
        """
        result = self.copy()
        
        for i in range(len(result.coordinates)):
            result.coordinates[i] = result.coordinates[i] % 1
            
        result.apply(tuple(numpy.argsort(a) for a in result.coordinates))
            
        return result
    
    @input_as_list
    def isolated(self, gaps, units = "cartesian"):
        """
        Generates an isolated representation of this grid.
        
        Symmetrically adds vacuum along all basis vectors such that
        resulting grid basis vectors are parallel to the initial ones.
        
        Args:
        
            gaps (array): size of the vacuum layer in each direction
            either in cartesian or in crystal units.
            
        Kwargs:
        
            units (str): units of the vacuum size, 'cartesian' or
            'crystal'
            
        Returns:
        
            A new isolated grid.
        """
        gaps = numpy.array(gaps, dtype = numpy.float64)
        if units == "cartesian":
            gaps /= ((self.vectors**2).sum(axis = 1)**.5)
        elif units == "crystal":
            pass
        else:
            raise ArgumentError("Unknown units: '{}'".format(str(units)))
        
        result = self.copy()
        
        gaps += 1
        result.vectors *= gaps[...,numpy.newaxis]
        
        for i in range(len(result.coordinates)):
            result.coordinates[i] /= gaps[i]
            result.coordinates[i] += (0.5*(gaps[i]-1)/gaps[i])
        
        return result
            
    @input_as_list
    def select(self, piece):
        """
        Selects a piece of this grid.
        
        Args:
        
            piece (array): fraction of the grid to be selected, see
            examples. The order of coordinates in ``piece`` is ``x_from, y_from, ..., z_from, x_to, y_to, ..., z_to``.
            
        Returns:
        
            A list of numpy arrays with bools defining whether particular
            grid point is selected or not.
            
        Example:
            
            >>> grid.select((0,0,0,1,1,1)) # select all grid points with coordinates within (0,1) range
            >>> grid.select(0,0,0,1,1,1) # a simplified version of above
            >>> grid.select(0,0,0,0.5,1,1) # select the 'left' part
            >>> grid.select(0.5,0,0,1,1,1) # select the 'right' part
        """
        if not len(piece) == 2*self.vectors.shape[0]:
            raise ArgumentError("Wrong coordinates array: expecting {:d} elements, found {:d}".format(
                2*self.vectors.shape[0], len(piece)
            ))
            
        piece = numpy.reshape(piece,(2,-1))
        p1 = numpy.amin(piece,axis = 0)
        p2 = numpy.amax(piece,axis = 0)
        return list( (c<mx) & (c>=mn) for c,mn,mx in zip(self.coordinates,p1,p2) )
        
    @input_as_list
    def apply(self, selection):
        """
        Applies selection to this grid.
        
        Inverse of ``Grid.discard``.
        
        Args:
        
            selection (array): seleted grid points.
            
        Example:
        
            >>> selection = grid.select((0,0,0,0.5,1,1)) # Selects species in the 'left' part of the grid.
            >>> grid.apply(selection) # Applies selection. Species outside the 'left' part are discarded.
        """
        selection = list(selection)
        slices = [slice(None,None,None)]*len(self.coordinates)
        
        for i in range(len(self.coordinates)):
            
            if not isinstance(selection[i],slice):
                selection[i] = numpy.array(selection[i])
            self.coordinates[i] = self.coordinates[i][selection[i]]
            
            # Set a valid slice
            slices[i] = selection[i]
            # Apply slice
            self.values = self.values[slices]
            # Revert slice
            slices[i] = slice(None,None,None)
        
    @input_as_list
    def discard(self, selection):
        """
        Removes specified points from this grid.
        
        Inverse of ``Grid.apply``.
        
        Args:
        
            selection (array): points to remove.
            
        Example:
        
            >>> selection = grid.select((0,0,0,0.5,1,1)) # Selects points in the 'left' part of the grid.
            >>> grid.discard(selection) # Discards selection. Points inside the 'left' part are removed.
        """
        self.apply(tuple(~numpy.array(i) for i in selection))

    @input_as_list
    def cut(self, piece):
        """
        Selects a piece of the grid and returns it as a smaller basis.
        
        Kwargs:
        
            piece (array): fraction of the grid to be selected. The order
            of coordinates in ``piece`` is ``x_from, y_from, ..., z_from, x_to, y_to, ..., z_to``.
            
        Returns:
        
            A smaller grid selected.
        """
        result = self.copy()
        result.apply(result.select(piece))
        
        piece = numpy.reshape(piece,(2,-1))
        p1 = numpy.amin(piece,axis = 0)
        p2 = numpy.amax(piece,axis = 0)
        
        for i in range(len(result.coordinates)):
            result.coordinates[i] -= p1[i]
            result.coordinates[i] /= (p2-p1)[i]
        result.vectors *= (p2-p1)[numpy.newaxis,:]
        return result
    
    @input_as_list
    def add(self, grids, fill = float("nan")):
        """
        Adds grid points from another grids to this one.
        
        Args:
        
            grids (arguments): grids to be merged with.
            
        Returns:
        
            A new grid with merged data.
        """
        dims = len(self.coordinates)
        grids = [self]+grids
        new_coordinates = []
        
        # Coordinates lookup tables
        coord2index = []
        
        # Calculate unique coordinates on the grid and lookup tables
        for j in range(dims):
            
            c = []
            for i in grids:
                c.append(i.coordinates[j])
                
            c = numpy.concatenate(c,axis = 0)
            unique_coordinates, lookup = numpy.unique(c, return_inverse = True)
            new_coordinates.append(unique_coordinates)
            coord2index.append(lookup)
        
        
        new_shape = tuple(a.shape[0] for a in new_coordinates)
        new_values = numpy.ones(new_shape + self.values.shape[dims:])*fill

        # Fill in the values
        offsets = [0]*dims
        for i in grids:
            
            location = tuple(c2i[o:o+c.shape[0]] for o, c2i, c in zip(offsets, coord2index, i.coordinates))
            location = numpy.ix_(*location)
            new_values[location] = i.values
            
            for j in range(len(offsets)):
                offsets[j] += i.coordinates[j].shape[0]
        
        return Grid(
            Basis(self.vectors, meta = self.meta),
            new_coordinates,
            new_values,
        )
    
    @input_as_list
    def stack(self, grids, vector = 'x', tolerance = 1e-10):
        """
        Stacks several grids along one of the vectors.
        
        Args:
        
            grids (list): grids to stack. Corresponding vectors of
            all grids being stacked should match.
            
        Kwargs:
        
            vector (str,int): a vector along which to stack, either 'x',
            'y', 'z' or an int specifying the vector.
        
            tolerance (float): a largest possible error in input grids'
            vectors
            
        Raises:
        
            ArgumentError: in the case of vector mismatch.
            
        Returns:
        
            A bigger grid containing all argument grids stacked.
        """
        grids = [self]+grids
        d = __xyz2i__(vector)
        dims = self.vectors.shape[0]
            
        otherVectors = list(range(grids[0].vectors.shape[0]))
        del otherVectors[d]
            
        basis = Basis.stack(*grids, vector = vector, tolerance = tolerance)
        
        for g in grids:
            if not type(g) in (Grid, Basis):
               raise ArgumentError('The object {} is not an instance of a Grid'.format(g))
        
        for i, g in enumerate(grids[1:]):
            if isinstance(g, Grid):
                for dim in otherVectors:
                    if not len(g.coordinates[dim]) == len(self.coordinates[dim]) or not numpy.all(g.coordinates[dim] == self.coordinates[dim]):
                        raise ArgumentError("Grid coordinates in dimension {:d} of cells 0 and {:d} are different".format(dim, i))
         
        values = numpy.concatenate(tuple(grid.values for grid in grids if isinstance(grid, Grid)), axis = d)
            
        stackingVectorsLen = numpy.array(tuple((grid.vectors[d]**2).sum(axis = -1)**.5 for grid in grids))
        shifts = numpy.cumsum(stackingVectorsLen)
        shifts = shifts/shifts[-1]
        
        # kx+b
        k = numpy.ones((len(grids),dims))
        k[:,d] = stackingVectorsLen/stackingVectorsLen.sum()
        b = numpy.zeros((len(grids),dims))
        b[:,d] = numpy.concatenate(((0,),shifts[:-1]))
        
        coordinates = []
        for dim in range(dims):
            if dim == d:
                coordinates.append(numpy.concatenate(tuple(
                    grid.coordinates[dim]*k[i,dim]+b[i,dim] for i,grid in enumerate(grids) if isinstance(grid, Grid)
                ),axis = 0))
            else:
                coordinates.append(self.coordinates[dim])
            
        return Grid(basis, coordinates, values)

    @input_as_list
    def reorder_vectors(self, new):
        """
        Reorders vectors. Does not change output of ``Grid.cartesian()``.
        
        Args:
        
            new (array): new mapping of vectors.
            
        Example:
        
            >>> grid.reorder_vectors(0, 1, 2) # does nothing
            >>> grid.reorder_vectors(1, 0, 2) # swaps first and second vectors.
            
        .. note::
        
            A call to this method does not modify the output of ``self.cartesian()``.
        """
        new = list(__xyz2i__(i) for i in new)
        Basis.reorder_vectors(self, new)
        self.coordinates = list(self.coordinates[n] for n in new)
        
        # Change values using swapaxes
        for i in range(len(new)):
            if not new[i] == i:
                self.values = self.values.swapaxes(i, new[i])
                new[new[i]] = new[i]
    
    def as_unitCell(self):
        """
        Converts this cell to a ``UnitCell``.
        
        Returns:
        
            A new ``UnitCell``.
        """
        c = self.explicit_coordinates()
        c = c.reshape((-1,c.shape[-1]))
        v = self.values.reshape((-1,)+self.values.shape[len(self.coordinates):])
        
        return UnitCell(Basis(self.vectors, meta = self.meta), c, v)
        
    def __interpolate__(self, points, driver = None, periodic = True, **kwargs):
        """
        Interpolates values at specified points and returns an array of
        interpolated values. By default uses ``scipy.interpolate.interpn``.
        
        Args:
        
            points (array): points to interpolate at.
            
        Kwargs:
        
            driver (func): interpolation driver.
            
            periodic (bool): employs periodicity of a unit cell.
            
            **kwargs: keywords to the driver.
            
        Returns:
        
            An array with values of corresponding shape.
        """

        if driver is None:
            from scipy import interpolate
            driver = interpolate.interpn
            
        normalized = self.normalized()
        
        if periodic:
            
            data_points = normalized.coordinates
            data_values = normalized.values
            
            # Avoid edge problems
            for i, a in enumerate(data_points):
                
                data_points[i] = numpy.insert(a,(0,a.size),(a[-1]-1.0,a[0]+1.0))
                
                left_slice = (slice(None),)*i + ((0,),) + (slice(None),)*(len(data_points)-i-1)
                left = data_values[left_slice]
                
                right_slice = (slice(None),)*i + ((-1,),) + (slice(None),)*(len(data_points)-i-1)
                right = data_values[right_slice]
                
                data_values = numpy.concatenate((left, data_values, right), axis = i)
                
            points = points % 1
        
        else:
            
            data_points = normalized.coordinates
            data_values = normalized.values
        
        # Interpolate
        return driver(data_points, data_values, points, **kwargs)

    def interpolate(self, points, driver = None, periodic = True, **kwargs):
        """
        Interpolates values at specified points and returns a grid.
        By default uses ``scipy.interpolate.interpn``.
        
        Args:
        
            points (array): points to interpolate at.
            
        Kwargs:
        
            driver (func): interpolation driver.
            
            periodic (bool): employs periodicity of a unit cell.
            
            kwargs: keywords to the driver.
            
        Returns:
        
            A grid with interpolated values.
        """
        # A dummy grid
        result = Grid(Basis(self.vectors, meta = self.meta), points, numpy.zeros(
            tuple(i.shape[0] for i in points) + (0,)
        ))
        
        result.values = self.__interpolate__(result.explicit_coordinates(), driver = driver, periodic = periodic, **kwargs)
        return result
        
    def interpolate_to_cell(self, points, driver = None, periodic = True, **kwargs):
        """
        Interpolates values at specified points and returns a unit cell.
        By default uses ``scipy.interpolate.interpn``.
        
        Args:
        
            points (array): points to interpolate at.
            
        Kwargs:
        
            driver (func): interpolation driver.
            
            periodic (bool): employs periodicity of a unit cell.
            
            kwargs: keywords to the driver.
            
        Returns:
        
            A unit cell interpolated values.
        """
        # A dummy unit cell
        result = UnitCell(Basis(self.vectors, meta = self.meta), points, points)
        
        result.values = self.__interpolate__(result.coordinates, driver = driver, periodic = periodic, **kwargs)
        return result
        
    def tetrahedron_density(self, points, resolved = False):
        """
        Convolves data to calculate density (of states). Uses the
        tetrahedron method from PRB 49, 16223 by E. Blochl et al. Works
        only in a 3D space.
        
        Args:
        
            points (array): values to calculate density at.
        
        Kwargs:
        
            resolved (bool): if True returns a spacially and index
            resolved density.
            
        Returns:
        
            A numpy array containing density: 1D if ``resolved == False``
            or a corresponding Grid if ``resolved == True``.
        """
        if not self.vectors.shape[0] == 3:
            raise ArgumentError("The tetrahedron density method is implemented only for 3D grids")
            
        initial = self.values
        points = numpy.array(points, dtype = numpy.float64)
        self.values = numpy.reshape(self.values, self.values.shape[:3]+(-1,))
        
        if resolved:
            
            raw = tetrahedron(self, points)
            self.values = initial
            return Grid(
                self,
                self.coordinates,
                numpy.reshape(raw, self.values.shape + points.shape),
            )
        
        else:
            
            raw = tetrahedron_plain(self, points)
            self.values = initial
            return raw

class TightBinding(object):
    
    def __init__(self, m):
        """
        A class representing tight binding (periodic) matrix.
        
        Args:
        
            m (dict): a tight binding matrix. The dict keys represent
            sets of integers corresponding to matrix block location
            while dict values are block matrices.
        """
        if len(m) == 0:
            raise ValueError("Empty input")
            
        self.__m__ = dict((k, numpy.array(v, dtype = numpy.complex)) for k,v in m.items() if numpy.count_nonzero(v)>0)
        
        self.dims = None
        self.msize = None
        d1 = None
        
        for k,v in self.__m__.items():
            
            msize = v.shape
            if not len(msize) == 2:
                raise ValueError("{} is not a 2D matrix: shape = {}".format(str(k), str(msize)))
                
            if not msize[0] == msize[1]:
                raise ValueError("{} is not a square matrix: shape = {}".format(str(k), str(msize)))
                
            if self.dims is None:
                self.dims = len(k)
                d1 = k
                self.msize = msize[0]
                
            elif not self.dims == len(k):
                raise ValueError("Inconsistent dimensions: {} vs {}".format(str(d1),str(k)))
                
            elif not self.msize == msize[0]:
                raise ValueError("Inconsistent matrix size: {:d} in {} vs {:d} in {}".format(self.msize, str(d1), msize[0], str(k)))
    
    def copy(self):
        """
        Calculates a copy.
        
        Returns:
        
            A (shallow) copy.
        """
        return TightBinding(self.__m__.copy())
        
    def __repr__(self):
        return str(self.__m__)
        
    def __foreach__(self, p):
        return TightBinding(
            dict((k,p(k,v)) for k,v in self.__m__.items())
        )
        
    @staticmethod
    def __tr_i__(i):
        return tuple(-ii for ii in i)
        
    def __eq__(self, other):
        return len((self-other).__m__) == 0
        
    def __neg__(self):
        return self.__foreach__(lambda k,v: -v)
        
    def __abs__(self):
        return self.__foreach__(lambda k,v: abs(v))
            
    def __add__(self, other):
        keys = set(self.__m__.keys()) | set(other.__m__.keys())
        result = {}
        for k in keys:
            result[k] = self.__m__.get(k,0) + other.__m__.get(k,0)
        return TightBinding(result)
        
    def __radd__(self, other):
        return self + other
        
    def __sub__(self, other):
        keys = set(self.__m__.keys()) | set(other.__m__.keys())
        result = {}
        for k in keys:
            result[k] = self.__m__.get(k,0) - other.__m__.get(k,0)
        return TightBinding(result)
        
    def __rsub__(self, other):
        return - self + other
        
    def __mul__(self, other):
        return self.__foreach__(lambda k,v: v*other)
        
    def __rmul__(self, other):
        return self*other
        
    def __div__(self, other):
        if isinstance(other, TightBinding):
            keys = set(self.__m__.keys()) | set(other.__m__.keys())
            result = {}
            for k in keys:
                result[k] = self.__m__.get(k,0) / other.__m__.get(k,0)
            return TightBinding(result)
        else:
            return self.__foreach__(lambda k,v: v/other)
        
    def __getitem__(self, key):
        if not isinstance(key, tuple):
            key = (key,)
            
        if key in self.__m__:
            return self.__m__[key]
            
        else:
            if not len(key) == self.dims:
                raise ValueError("Argument number mismatch: found {:d}, required {:d}".format(len(key), self.dims))
                
            return numpy.zeros((self.msize,self.msize), dtype = numpy.complex)
            
    def __setitem__(self, key, item):
        if not isinstance(key, tuple):
            key = (key,)
            
        if not len(key) == self.dims:
            raise ValueError("Argument number mismatch: found {:d}, required {:d}".format(len(key), self.dims))
            
        item = numpy.array(item, dtype = numpy.complex)
        
        if not len(item.shape) == 2:
            raise ValueError("Not a 2D matrix: shape = {}".format(str(item.shape)))
            
        if not item.shape[0] == self.msize or not item.shape[1] == self.msize:
            raise ValueError("Wrong dimensions: shape = {}".format(str(item.shape)))
                
        self.__m__[key] = item
        
    def apply(self, mask):
        """
        Applies a mask to the tight binding.
        
        Returns:
        
            A new instance of tight binding with the mask applied.
        """
        return TightBinding(dict(
            (k, v[mask,:][:,mask]) for k,v in self.__m__.items()
        ))
        
    def tr(self):
        """
        Calculates transposed matrix.
        
        Returns:
        
            A transposed of the tight binding matrix.
        """
        result = {}
        for k in self.__m__.keys():
            result[TightBinding.__tr_i__(k)] = numpy.transpose(self.__m__[k])
            
        return TightBinding(result)
        
    def cc(self):
        """
        Calculates complex conjugate.
        
        Returns:
        
            A complex conjugate of the tight binding matrix.
        """
        result = self.__m__.copy()
        for k,v in result.items():
            result[k] = numpy.conj(v)
            
        return TightBinding(result)
        
    def hc(self):
        """
        Calculates Hermitian conjugate.
        
        Returns:
        
            A Hermitian conjugate of the tight binding matrix.
        """
        return self.tr().cc()
        
    def absmax(self):
        """
        Retrieves maximum value by modulus.
        
        Returns:
        
            A float with the maximum value.
        """
        mx = 0
        for k,v in self.__m__.items():
            mx = max(mx, abs(v).max())
        return mx
            
    def hermitian_error(self):
        """
        Calculates largest non-hermitian element of the Hamiltonian.
        
        Returns:
        
            A float giving a measure of the matrix non-hermitianity.
        """
        return (self - self.hc()).absmax()
        
    def fourier(self, k, index = None):
        """
        Performs Fourier transform.
        
        Args:
        
            k (float): the wave number or a wave vector.
            
        Kwargs:
        
            index (int): index to transform; if None transforms along
            first ``len(k)'' indeces.
            
        Returns:
        
            Transformed tight binding matrix.
        """
        if not index is None:
            
            new_data = {}
            
            for key, value in self.__m__.items():
                
                key2 = tuple(key[:index] + key[index+1:])
                matrix = value*numpy.exp(2j*numpy.pi*key[index]*k)
                
                if key2 in new_data:
                    new_data[key2] += matrix
                    
                else:
                    new_data[key2] = matrix
                    
            return TightBinding(new_data)
            
        else:
            
            result = self
            for i in k:
                result = result.fourier(i, index = 0)
            return result
            
    def diagonal(self):
        """
        Retrieves diagonal block.
        
        Returns:
        
            The diagonal block of the tight binding.
        """
        return self[(0,)*self.dims]
        
    def is_1DNN(self):
        """
        Determines if it is a valid 1D nearest neighbour matrix.
            
        Returns:
        
            True if it is a valid one.
        """
        if not self.dims == 1:
            return False
            
        if not set(self.__m__.keys()) <= set(((0,),(1,),(-1,))):
            return False
        
        return True
        
    def gf(self, energy, b = None, direction = 'negative', skip_checks = False, tolerance = 1e-12):
        """
        Calculates the Green's function matrix.
        
        Args:
        
            energy (complex): energy to calculate at;

        Kwargs:
        
            b (TightBinding): the right-hand side of a generalized
            eigenvalue problem;
            
            direction (str): either 'positive' or 'negative' - the
            direction for the GF;
            
            skip_checks (bool): whether to skip the checks of the setup;
            
            tolerance (float): tolerance for Green's function iterations.
            
        Returns:
        
            A matrix with the Green's function.
        """
        
        if b is None:
            b = self.eye()
            
        if not skip_checks:
            if not self.is_1DNN():
                raise ValueError("Not a 1D NN tight binding")
            if not b.is_1DNN():
                raise ValueError("'b' is not a 1D NN tight binding")
            
        if direction == 'positive':
            return greens_function(
                energy+0j,
                self[0],
                self[1],
                b[0],
                b[1],
                tolerance = tolerance,
            )
            
        elif direction == 'negative':
            return greens_function(
                energy+0j,
                self[0],
                self[-1],
                b[0],
                b[-1],
                tolerance = tolerance,
            )
            
        else:
            raise ValueError("Unknown value of the direction: {}".format(direction))
            
    def eig_path(self, pts, b = None):
        """
        Calculates eigenvalues along a path in k space.
        
        Args:
        
            pts (array): an array containing k-points to calculate at;
            
        Kwargs:
            
            b (TightBinding): the rhs of a generailzed eigenvalue problem;
        
        Returns:
        
            Eigenvalues in a multidimensional array.
        """
        result = []
        for i in pts:
            
            hh = self.fourier(i).__m__.values()[0]
            
            if not b is None:
                bb = b.fourier(i).__m__.values()[0]
                
            else:
                bb = None
                
            result.append(linalg.eigvalsh(hh, b = bb))
        return numpy.array(result)
        
    def eye(self):
        """
        Generates an eye tight binding matrix.
        
        Args:
        
            like (TightBinding): the prototype matrix;
            
        Returns:
        
            A TightBinding of the same structure as input.
        """
        return TightBinding({
            (0,)*self.dims : numpy.eye(self.msize),
        })
        
    def super(self, size, dim):
        """
        Creates a supercell version of this tight binding.
        
        Args:
        
            size (int): a multiple to increase the tight binding;
            
            dim (int): dimension along which to increase the tight binding.
            
        Returns:
        
            A supercell tight binding.
        """
        result = {}
        for k,v in self.__m__.items():
            for i in range(size):
                j = k[dim]+i
                new_k = k[:dim] + (j/size,) + k[dim+1:]
                
                if not new_k in result:
                    result[new_k] = numpy.zeros((self.msize*size,self.msize*size), dtype = numpy.complex)
                
                j = j % size
                result[new_k][i*self.msize:(i+1)*self.msize,j*self.msize:(j+1)*self.msize] = v
                
        return TightBinding(result)
        
    def inverted(self, dim = 0):
        """
        Creates a space-inverted version of self.
        
        Kwargs:
        
            dim (int): dimension to invert;
            
        Returns:
        
            An inverted version of self.
        """
        return TightBinding(dict(
            (k[:dim] + (-k[dim],) + k[dim+1:],v) for k,v in self.__m__.items()
        ))
        
    def periodic_device(self, size = 1):
        """
        Initializes a periodic device with 2 identical leads and no
        scattering region.
        
        Kwargs:
        
            size (int): number of units to include into a scattering
            region;
        
        Returns:
        
            A periodic 2-terminal device.
        """
        if not self.is_1DNN():
            raise ValueError("Not a 1D NN tight binding")
            
        return MultiterminalDevice(self.super(size,0).diagonal(), [self, self.inverted()])

class MultiterminalDevice(object):
    
    def __init__(self, center, leads, connections = None):
        """
        Describes a multiterminal 1D device.
        
        Args:
        
            center (matrix): a matrix of the center part of device;
            
            leads (array): the semi-infinite leads connected to a device;
            
        Kwargs:
        
            connections (array): corresponding connections of the leads.
        """
        self.center = numpy.array(center, dtype = numpy.complex)
        self.leads = leads
        
        for i, l in enumerate(leads):
            if not l.is_1DNN():
                raise ValueError("Lead #{:d} is not a valid 1D NN".format(i))
        
        if connections is None:
            
            self.connections = []
            
            if len(leads) > 2:
                raise ValueError("Could not guess connections of more than 2 leads")
                
            if len(leads) > 0:
                self.connections.append(numpy.dot(
                    self.leads[0][1],
                    numpy.eye(self.leads[0].msize, M = self.center.shape[0])
                ))
                
            if len(leads) > 1:
                n = self.leads[1].msize
                m = self.center.shape[0]
                self.connections.append(numpy.dot(
                    self.leads[1][1],
                    numpy.eye(n, M = m, k = m-n),
                ))
                
        else:
            
            self.connections = connections
    
    def eye(self):
        """
        Generates an eye multiterminal device.
        
        Args:
        
            like (MutiterminalDevice): the prototype;
            
        Returns:
        
            A MultiterminalDevice of the same structure as input.
        """
        return MultiterminalDevice(
            numpy.eye(self.center.shape[0]),
            list(i.eye() for i in self.leads),
            connections = list(numpy.zeros(i.shape) for i in self.connections),
        )

    def __se__(self, energy, i, b, tolerance = 1e-12):
            
        G = self.leads[i].gf(
            energy,
            b = b.leads[i],
            direction = 'negative',
            skip_checks = True,
            tolerance = tolerance,
        )
        
        wSH1 = energy*b.connections[i] - self.connections[i]
        wSH2 = energy*b.connections[i].conj().T - self.connections[i].conj().T
        
        return numpy.dot(numpy.dot(wSH2,G),wSH1)

    def gf(self, energy, b = None, tolerance = 1e-12):
        """
        Calculates the Green's function matrix.
        
        Args:
        
            energy (complex): energy to calculate at;

        Kwargs:
        
            b (TightBinding): the right-hand side of a generalized
            eigenvalue problem;
            
            tolerance (float): tolerance for Green's function iterations.
            
        Returns:
        
            A matrix with the Green's function.
        """
        if b is None:
            b = self.eye()
            
        gi = energy*b.center - self.center
        for i in range(len(self.leads)):
            gi -= self.__se__(energy, i, b, tolerance = tolerance)
            
        return linalg.inv(gi)

from __future__ import print_function
import numpy as np
import pandas as pd
import os

from .time_advance import func_index_te

AtomicNumbers = pd.Series(np.arange(28)+1,
                         index=['H' ,'He',
                                'Li','Be','B' ,'C' ,'N' ,'O' ,'F' ,'Ne',
                                'Na','Mg','Al','Si','P' ,'S' ,'Cl','Ar',
                                'K' ,'Ca','Sc','Ti','V' ,'Cr','Mn','Fe','Co','Ni',
                                ])

def read_atomic_data(elements=['H', 'He', 'C',     # twelve most abundant elements
                               'N', 'O', 'Ne',
                               'Mg', 'Si', 'S', 
                               'Ar', 'Ca', 'Fe', ] , 
                     data_directory= 'sunnei/AtomicData',   # not robust!  Works when calling from the directory that sunnei is in
                     screen_output=False):

    '''
    This routine reads in the atomic data to be used for the
    non-equilibrium ionization calculations.
 
    Instructions for generating atomic data files
    =============================================
    
    The atomic data files are generated from the routines described by
    Shen et al. (2015) and are available at:
    
    https://github.com/ionizationcalc/time_dependent_fortran
    
    First, run the IDL routine 'pro_write_ionizrecomb_rate.pro' in the
    subdirectory sswidl_read_chianti with optional parameters: nte
    (number of temperature bins, default=501), te_low (low log
    temperature, default=4.0), and te_high (high log temperature,
    default=9.0) to get an ionization rate table.  The routine outputs
    the file "ionrecomb_rate.dat" which is a text file containing the
    ionization and recombination rates as a function of temperature.
    This routine requires the atomic database Chianti to be installed
    in IDL.

    Second, compile the Fortran routine 'create_eigenvmatrix.f90'.
    With the Intel mkl libraries it is compiled as: "ifort -mkl
    create_eigenvmatrix.f90 -o create.out" which can then be run with
    the command "./create.out".  This routine outputs all the
    eigenvalue tables for the first 28 elements (H to Ni).

    As of 2016 April 7, data from Chianti 8 is included in the
    CMEheat/AtomicData subdirectory.
    '''

    if screen_output:
        print('read_atomic_data: beginning program')
    
    from scipy.io import FortranFile

    '''
    Begin a loop to read in the atomic data files needed for the
    non-equilibrium ionization modeling.  The information will be
    stored in the atomic_data dictionary.

    For the first element in the loop, the information that should be
    the same for each element will be stored at the top level of the
    dictionary.  This includes the temperature grid, the number of
    temperatures, and the number of elements.

    For all elements, read in and store the arrays containing the
    equilibrium state, the eigenvalues, the eigenvectors, and the
    eigenvector inverses.
    '''

    atomic_data = {}
    
    first_element_in_loop = True

    for element in elements:

        if screen_output:
            print('read_atomic_data: '+element)

        AtomicNumber = AtomicNumbers[element]
        nstates = AtomicNumber + 1

        filename = data_directory + '/' + element.lower() + 'eigen.dat'
        H = FortranFile(filename, 'r')

        nte, nelems = H.read_ints(np.int32)
        temperatures = H.read_reals(np.float64)
        equistate = H.read_reals(np.float64).reshape((nte,nstates))
        eigenvalues = H.read_reals(np.float64).reshape((nte,nstates))
        eigenvector = H.read_reals(np.float64).reshape((nte,nstates,nstates))
        eigenvector_inv = H.read_reals(np.float64).reshape((nte,nstates,nstates))
        c_rate = H.read_reals(np.float64).reshape((nte,nstates))
        r_rate = H.read_reals(np.float64).reshape((nte,nstates))      
        
        if first_element_in_loop:
            atomic_data['nte'] = nte
            atomic_data['nelems'] = nelems  # Probably not used but store anyway
            atomic_data['temperatures'] = temperatures
            first_element_in_loop = False
        else: 
            assert nte == atomic_data['nte'], 'Atomic data files have different number of temperature levels: '+element
            assert nelems == atomic_data['nelems'], 'Atomic data files have different number of elements: '+element
            assert np.allclose(atomic_data['temperatures'],temperatures), 'Atomic data files have different temperature bins'

        atomic_data[element] = {'element':element,
                                'AtomicNumber':AtomicNumber,
                                'nstates':nstates,
                                'equistate':equistate,
                                'eigenvalues':eigenvalues,
                                'eigenvector':eigenvector,
                                'eigenvector_inv':eigenvector_inv,
                                'ionization_rate':c_rate,
                                'recombination_rate':r_rate,
                                }
        
    if screen_output:
        print('read_atomic_data: '+str(len(elements))+' elements read in')
        print('read_atomic_data: complete')

    return atomic_data

def create_ChargeStates_dictionary(elements, 
                                   temperature=0, 
                                   AtomicData=None):
    '''
    Create a dictionary that contains the initial charge state
    distributions for the chosen elements.

    If the temperature is not specified as an input, then this
    function will assume that every element is completely neutral.

    If the temperature is specified, then each charge state will be
    initialized with the equilibrium ionization charge states for that
    temperature.

    The AtomicData dictionary may be optionally included as the third
    argument so that it is not necessary to read it in more than once.
    If AtomicData is not an input, then it will be read in.

    For each element, ChargeStates[element] records the ionization
    fraction for each ionization state.

    ChargeStates[element][0] --> fraction that is neutral
    ChargeStates[element][1] --> fraction that is singly ionized
    ChargeStates[element][2] --> fraction that is doubly ionized

    ChargeStates['H'] = [1.0, 0.0] <-- completely neutral    
    ChargeStates['H'] = [0.0, 1.0] <-- fully ionized 
    
    ChargeStates['He'] = [1.0, 0.0, 0.0] <-- completely neutral
    ChargeStates['He'] = [0.0, 1.0, 0.0] <-- all singly ionized
    ChargeStates['He'] = [0.0, 0.0, 1.0] <-- fully ionized

    The sum of the charge states for a particular element should equal
    one (to within roundoff or numerical error).  
    '''

    ChargeStates = {}
    
    # Initialize the charge state distribution for each element by
    # assuming it is entirely neutral

    for element in elements:
        ChargeStates[element] = np.zeros(AtomicNumbers[element]+1)
        ChargeStates[element][0]=1
    
    # If the temperature is specified, then initialize this dictionary
    # with the equilibrium charge states for that temperature.

    # For future, could replace part of this loop with the new
    # EquilChargeStates function below

    if temperature>0: 
        if AtomicData == None:
            AtomicData = read_atomic_data(elements)
        TemperatureIndex = func_index_te(temperature, AtomicData['temperatures'])
        for element in elements:
            AtomicNumber = AtomicNumbers[element]
            ChargeStates[element] = AtomicData[element]['equistate'][TemperatureIndex,:]
            # Make sure that the charge states are nonnegative
            for istate in range(ChargeStates[element].size):
                if ChargeStates[element][istate] < 1e-14:
                    ChargeStates[element][istate] = 0.0
                elif ChargeStates[element][istate] > 1.0 and ChargeStates[element][istate] < 1.0 + 9e-10:
                    ChargeStates[element][istate] = 1.0
            
    # Test that the charge state distribution for each element sums to one

    tol = 1e-9
    for element in elements:
        val = np.sum(ChargeStates[element])
        assert (val>1-tol) & (val<1+tol), 'Initial charge states do not sum to one for '+element

    return ChargeStates

def ReformatChargeStateList(ChargeStateList, elements, nsteps):
    '''
    Changes the way charge state data is stored.  

    The original time advance creates a list of the charge state
    dictionaries so that charge state information is accessed like:

    ChargeStateList[TimeIndex][element][ChargeStateIndex]

    However, this interface does not allow us to use a range of time
    indices for a particular element.  This function takes a list of
    charge state dictionaries from the original time advance, and
    changes them into a dictionary with each element as a key to
    access a NumPy array with the charge state information over time.

    ChargeStates[element][TimeIndex,ChargeStateIndex]
    '''

    ChargeStates = {}  
    for element in elements:        
        ncharge = AtomicNumbers[element]+1
        ChargeStates[element] = np.zeros([nsteps+1,ncharge])
        for istep in range(nsteps+1):
            ChargeStates[element][istep,0:ncharge] = \
                ChargeStateList[istep][element][0:ncharge]
    return ChargeStates

def EquilChargeStates(temperature, element, AtomicData=None):
    '''
    Returns an array of the equilibrium charge states for an element
    at temperature T.
    '''

    if AtomicData.__class__ != dict:
        AtomicData = read_atomic_data([element])

    TemperatureIndex = func_index_te(temperature, AtomicData['temperatures'])
    ChargeStates = AtomicData[element]['equistate'][TemperatureIndex,:]

    for istate in range(ChargeStates.size):
        if ChargeStates[istate] < 1e-14:
            ChargeStates[istate] = 0.0
        elif ChargeStates[istate] > 1.0 and ChargeStates[element][istate] < 1.0 + 9e-10:
            ChargeStates[istate] = 1.0           

    return ChargeStates
            

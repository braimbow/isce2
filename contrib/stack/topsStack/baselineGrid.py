#!/usr/bin/env python3
# Author: Piyush Agram
# Copyright 2016
#Heresh Fattahi, Adopted for stack

import argparse
import logging
import datetime
import isce
import isceobj
import mroipac
import os
import s1a_isce_utils as ut

def createParser():
    parser = argparse.ArgumentParser( description='Use polynomial offsets and create burst by burst interferograms')

    parser.add_argument('-m', '--reference', dest='reference', type=str, required=True,
            help='Directory with reference acquisition')

    parser.add_argument('-s', '--secondary', dest='secondary', type=str, required=True,
            help='Directory with secondary acquisition')

    parser.add_argument('-b', '--baseline_file', dest='baselineFile', type=str, required=True,
                help='An output text file which contains the computed baseline')


    return parser

def cmdLineParse(iargs = None):
    parser = createParser()
    return parser.parse_args(args=iargs)


def getMergedOrbit(product):
    from isceobj.Orbit.Orbit import Orbit

    ###Create merged orbit
    orb = Orbit()
    orb.configure()

    burst = product[0].bursts[0]
    #Add first burst orbit to begin with
    for sv in burst.orbit:
            orb.addStateVector(sv)


    for pp in product:
        ##Add all state vectors
        for bb in pp.bursts:
            for sv in bb.orbit:
                if (sv.time< orb.minTime) or (sv.time > orb.maxTime):
                    orb.addStateVector(sv)

            bb.orbit = orb

    return orb

#logger = logging.getLogger('isce.topsinsar.runPreprocessor')

def main(iargs=None):
    '''Compute baseline.
    '''
    inps=cmdLineParse(iargs)
    from isceobj.Planet.Planet import Planet
    import numpy as np


    referenceSwathList = ut.getSwathList(inps.reference)
    secondarySwathList = ut.getSwathList(inps.secondary)
    swathList = list(sorted(set(referenceSwathList+secondarySwathList)))

    #catalog = isceobj.Catalog.createCatalog(self._insar.procDoc.name)
    baselineDir = os.path.dirname(inps.baselineFile)
    if baselineDir != '':
        os.makedirs(baselineDir, exist_ok=True)

    referenceswaths = []
    secondaryswaths = []
    for swath in swathList:
        referencexml = os.path.join( inps.reference, 'IW{0}.xml'.format(swath))
        secondaryxml = os.path.join( inps.secondary, 'IW{0}.xml'.format(swath))

        if os.path.exists(referencexml) and os.path.exists(secondaryxml):

            reference = ut.loadProduct(os.path.join(inps.reference , 'IW{0}.xml'.format(swath)))
            secondary = ut.loadProduct(os.path.join(inps.secondary , 'IW{0}.xml'.format(swath)))

            referenceswaths.append(reference)
            secondaryswaths.append(secondary)


    refElp = Planet(pname='Earth').ellipsoid
    mStartingRange = min([x.startingRange for x in referenceswaths])
    mFarRange = max([x.farRange for x in referenceswaths])
    mSensingStart = min([x.sensingStart for x in referenceswaths])
    mSensingStop = max([x.sensingStop for x in referenceswaths])
    mOrb = getMergedOrbit(referenceswaths)

    dr = referenceswaths[0].bursts[0].rangePixelSize
    dt = referenceswaths[0].bursts[0].azimuthTimeInterval

    nPixels = int(np.round( (mFarRange - mStartingRange)/dr)) + 1
    nLines = int(np.round( (mSensingStop - mSensingStart).total_seconds() / dt)) + 1

    sOrb = getMergedOrbit(secondaryswaths)

    rangeLimits = mFarRange - mStartingRange
    nRange = int(np.ceil(rangeLimits/7000.))
    slantRange = mStartingRange + np.arange(nRange) * rangeLimits / (nRange - 1.0)


    azimuthLimits = (mSensingStop - mSensingStart).total_seconds()
    nAzimuth = int(np.ceil(azimuthLimits))
    azimuthTime = [mSensingStart + datetime.timedelta(seconds= x * azimuthLimits/(nAzimuth-1.0))  for x in range(nAzimuth)]

    
    Bpar = np.zeros(nRange, dtype=np.float32)
    Bperp = np.zeros(nRange, dtype=np.float32)

    fid = open(inps.baselineFile, 'wb')
    print('Baseline file {0} dims: {1}L x {2}P'.format(inps.baselineFile, nAzimuth, nRange))

    if inps.reference == inps.secondary:
        Bperp = np.zeros((nAzimuth,nRange), dtype=np.float32)
        Bperp.tofile(fid)
    else:
        for ii, taz in enumerate(azimuthTime):

            referenceSV = mOrb.interpolate(taz, method='hermite')
            mxyz = np.array(referenceSV.getPosition())
            mvel = np.array(referenceSV.getVelocity())
            
            for jj, rng in enumerate(slantRange):
    
                target = mOrb.rdr2geo(taz, rng)
    
                targxyz = np.array(refElp.LLH(target[0], target[1], target[2]).ecef().tolist())
                slvTime,slvrng = sOrb.geo2rdr(target)
    
                secondarySV = sOrb.interpolateOrbit(slvTime, method='hermite')
    
                sxyz = np.array( secondarySV.getPosition())
    
                aa = np.linalg.norm(sxyz-mxyz)
                costheta = (rng*rng + aa*aa - slvrng*slvrng)/(2.*rng*aa)
    
                Bpar[jj] = aa*costheta
    
                perp = aa * np.sqrt(1 - costheta*costheta)
                direction = np.sign(np.dot( np.cross(targxyz-mxyz, sxyz-mxyz), mvel))
                Bperp[jj] = direction*perp
    
            Bperp.tofile(fid)
    
    fid.close()


    ####Write XML
    img = isceobj.createImage()
    img.setFilename( inps.baselineFile)
    img.bands = 1
    img.scheme = 'BIP'
    img.dataType = 'FLOAT'
    img.setWidth(nRange)
    img.setAccessMode('READ')
    img.setLength(nAzimuth)
    img.renderHdr()
    img.renderVRT()

    ###Create oversampled VRT file
    cmd = 'gdal_translate -of VRT -ot Float32 -r bilinear -outsize {xsize} {ysize} {infile}.vrt {infile}.full.vrt'.format(xsize=nPixels, ysize=nLines, infile=inps.baselineFile)

    status = os.system(cmd)
    if status:
        raise Exception('cmd: {0} Failed'.format(cmd))
            
if __name__ == '__main__':
    '''
    Main driver.
    '''
    main()


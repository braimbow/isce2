/**
 * @file cuAmpcorController.cu
 * @brief Implementations of cuAmpcorController
 */

// my declaration
#include "cuAmpcorController.h"

// dependencies
#include "GDALImage.h"
#include "cuArrays.h"
#include "cudaUtil.h"
#include "cuAmpcorChunk.h"
#include "cuAmpcorUtil.h"
#include <iostream>

// constructor
cuAmpcorController::cuAmpcorController()
{
    // create a new set of parameters
    param = new cuAmpcorParameter();
}

// destructor
cuAmpcorController::~cuAmpcorController()
{
    delete param;
}


/**
 *  Run ampcor
 *
 *
 */
void cuAmpcorController::runAmpcor()
{
    // set the gpu id
    param->deviceID = gpuDeviceInit(param->deviceID);
    // initialize the gdal driver
    GDALAllRegister();
    // reference and secondary images; use band=1 as default
    // TODO: selecting band
    GDALImage *referenceImage = new GDALImage(param->referenceImageName, 1, param->mmapSizeInGB);
    GDALImage *secondaryImage = new GDALImage(param->secondaryImageName, 1, param->mmapSizeInGB);

    cuArrays<float2> *offsetImage, *offsetImageRun;
    cuArrays<float> *snrImage, *snrImageRun;
    cuArrays<float3> *covImage, *covImageRun;

    // nWindowsDownRun is defined as numberChunk * numberWindowInChunk
    // It may be bigger than the actual number of windows
    int nWindowsDownRun = param->numberChunkDown * param->numberWindowDownInChunk;
    int nWindowsAcrossRun = param->numberChunkAcross * param->numberWindowAcrossInChunk;

    offsetImageRun = new cuArrays<float2>(nWindowsDownRun, nWindowsAcrossRun);
    offsetImageRun->allocate();

    snrImageRun = new cuArrays<float>(nWindowsDownRun, nWindowsAcrossRun);
    snrImageRun->allocate();

    covImageRun = new cuArrays<float3>(nWindowsDownRun, nWindowsAcrossRun);
    covImageRun->allocate();

    // Offset fields.
    offsetImage = new cuArrays<float2>(param->numberWindowDown, param->numberWindowAcross);
    offsetImage->allocate();

    // SNR.
    snrImage = new cuArrays<float>(param->numberWindowDown, param->numberWindowAcross);
    snrImage->allocate();

    // Variance.
    covImage = new cuArrays<float3>(param->numberWindowDown, param->numberWindowAcross);
    covImage->allocate();

    // set up the cuda streams
    cudaStream_t streams[param->nStreams];
    cuAmpcorChunk *chunk[param->nStreams];
    // iterate over cuda streams
    for(int ist=0; ist<param->nStreams; ist++)
    {
        // create each stream
        checkCudaErrors(cudaStreamCreate(&streams[ist]));
        // create the chunk processor for each stream
        chunk[ist]= new cuAmpcorChunk(param, referenceImage, secondaryImage,
            offsetImageRun, snrImageRun, covImageRun,
            streams[ist]);

    }

    int nChunksDown = param->numberChunkDown;
    int nChunksAcross = param->numberChunkAcross;

    // report info
    std::cout << "Total number of windows (azimuth x range):  "
        << param->numberWindowDown << " x " << param->numberWindowAcross
        << std::endl;
    std::cout << "to be processed in the number of chunks: "
        << nChunksDown << " x " << nChunksAcross  << std::endl;

    // iterative over chunks down
    for(int i = 0; i<nChunksDown; i++)
    {
        std::cout << "Processing chunk (" << i <<", x" << ") out of " << nChunksDown << std::endl;
        // iterate over chunks across
        for(int j=0; j<nChunksAcross; j+=param->nStreams)
        {
            // iterate over cuda streams to process chunks
            for(int ist = 0; ist < param->nStreams; ist++)
            {
                int chunkIdxAcross = j+ist;
                if(chunkIdxAcross < nChunksAcross) {
                    chunk[ist]->run(i, chunkIdxAcross);
                }
            }
        }
    }

    // wait all streams are done
    cudaDeviceSynchronize();

    // extraction of the run images to output images
    cuArraysCopyExtract(offsetImageRun, offsetImage, make_int2(0,0), streams[0]);
    cuArraysCopyExtract(snrImageRun, snrImage, make_int2(0,0), streams[0]);
    cuArraysCopyExtract(covImageRun, covImage, make_int2(0,0), streams[0]);
    // save outputs to files
    offsetImage->outputToFile(param->offsetImageName, streams[0]);
    snrImage->outputToFile(param->snrImageName, streams[0]);
    covImage->outputToFile(param->covImageName, streams[0]);
    // also save the gross offsets
    outputGrossOffsets();

    // Delete arrays.
    delete offsetImage;
    delete snrImage;
    delete covImage;

    delete offsetImageRun;
    delete snrImageRun;
    delete covImageRun;

    for (int ist=0; ist<param->nStreams; ist++)
    {
        checkCudaErrors(cudaStreamDestroy(streams[ist]));
        delete chunk[ist];
    }

    delete referenceImage;
    delete secondaryImage;

}

/**
 * Output gross offset fields
 */
void cuAmpcorController::outputGrossOffsets()
{
    cuArrays<float2> *grossOffsets = new cuArrays<float2>(param->numberWindowDown, param->numberWindowAcross);
    grossOffsets->allocateHost();

    for(int i=0; i< param->numberWindows; i++)
        grossOffsets->hostData[i] = make_float2(param->grossOffsetDown[i], param->grossOffsetAcross[i]);
    grossOffsets->outputHostToFile(param->grossOffsetImageName);
    delete grossOffsets;
}

// end of file

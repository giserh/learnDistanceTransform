import sys
import core
import skneuro.blockwise_filters as filters
import argparse
import vigra
import numpy
import matplotlib.pyplot as plt
import logging as log
import loaddata
import time
import multiprocessing
import os


def create_dummy_feature_list():
    """Generate a list with function calls of features that shall be computed.

    Each list item is of the form [number_of_features, function_name, function_args].
    :return: List with features.
    """
    return [[1, filters.blockwiseGaussianSmoothing, 1.0],
            [1, filters.blockwiseGaussianSmoothing, 2.0],
            [1, filters.blockwiseGaussianSmoothing, 4.0],
            [1, filters.blockwiseGaussianGradientMagnitude, 1.0],
            [1, filters.blockwiseGaussianGradientMagnitude, 2.0],
            [1, filters.blockwiseGaussianGradientMagnitude, 4.0],
            [3, filters.blockwiseHessianOfGaussianSortedEigenvalues, 1.0],
            [3, filters.blockwiseHessianOfGaussianSortedEigenvalues, 2.0],
            [3, filters.blockwiseHessianOfGaussianSortedEigenvalues, 4.0],
            [1, filters.blockwiseLaplacianOfGaussian, 1.0],
            [1, filters.blockwiseLaplacianOfGaussian, 2.0],
            [1, filters.blockwiseLaplacianOfGaussian, 4.0],
            [3, filters.blockwiseStructureTensorSortedEigenvalues, 0.5, 1.0],
            [3, filters.blockwiseStructureTensorSortedEigenvalues, 1.0, 2.0],
            [3, filters.blockwiseStructureTensorSortedEigenvalues, 2.0, 4.0]]


def show_plots(shape, plots, interpolation="bilinear", titles=None):
    """Create a plot of the given shape and show the plots.

    :param shape: 2-tuple of integers
    :param plots: iterable of plots
    :param interpolation: interpolation argument to imshow
    """
    if titles is None:
        titles = []
    if len(titles) < len(plots):
        titles += [""] * (len(plots) - len(titles))
    assert 2 == len(shape)
    assert shape[0]*shape[1] == len(plots)
    assert len(titles) == len(plots)

    fig, rows = plt.subplots(*shape)
    for i, p in enumerate(plots):
        ind0, ind1 = numpy.unravel_index(i, shape)
        if shape[0] == 1:
            ax = rows[ind1]
        elif shape[1] == 1:
            ax = rows[ind0]
        else:
            ax = rows[ind0][ind1]
        ax.imshow(p, interpolation=interpolation)
        ax.set_title(titles[i])
    plt.show()


def TESTHYSTERESIS(lp_data):
    """

    :param lp_data:
    :return:
    """
    raw = lp_data.get_raw_train()
    hog1 = lp_data.get_feature_train(8)
    hys1 = vigra.filters.hysteresisThreshold(hog1, 0.4, 0.0125).astype(numpy.float32)

    sl = numpy.index_exp[:, :, 10]
    show_plots((1, 3), (raw[sl], hog1[sl], hys1[sl]))


def TESTCOMPARE(lp_data):
    """

    :param lp_data:
    :return:
    """
    sh = (100, 100, 100)
    dists_test = lp_data.get_data_y("test", "dists").reshape(sh)

    cap = 5
    dists_test[dists_test > cap] = cap
    allowed_vals = sorted(numpy.unique(dists_test))

    pred_inv = vigra.readHDF5("cache/pred_cap_lam_01.h5", "pred").reshape(sh)
    pred_inv_nearest = core.round_to_nearest(pred_inv, allowed_vals)

    sl = numpy.index_exp[:, :, 50]
    show_plots((1, 3),
               (dists_test[sl], pred_inv[sl], pred_inv_nearest[sl]),
               titles=["dists", "pred", "pred_rounded"],
               interpolation="nearest")


def TESTGM(lp_data, njobs=1):
    """

    :param lp_data:
    :return:
    """
    assert isinstance(lp_data, core.LPData)

    result_file_name = "scale_results.txt"

    # Create a list with all scales that are tried.
    scales_un = [0.25, 0.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]
    scales_bin = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    scales_diag_2 = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    scales_diag_3 = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    scales = [[a, b, c, d] for a in scales_un for b in scales_bin for c in scales_diag_2 for d in scales_diag_3]

    # Each process takes one scale, builds the graphical model and computes the rand index.
    def worker(qu_in, qu_out):
        while True:
            i, s = qu_in.get()
            r = lp_data.build_gm_dists(scale_un=s[0], scale_bin=s[1], scale_diag_2=s[2], scale_diag_3=s[3])
            print "[%s] Score %f for the scales" % (time.strftime("%H:%M:%S"), r), s
            qu_out.put((i, s, r))
            qu_in.task_done()

    # One process gathers the results and stores them in a file.
    def gatherer(qu_out):
        max_r = 0
        if os.path.isfile(result_file_name):
            os.remove(result_file_name)
        while True:
            i, s, r = qu_out.get()
            with open(result_file_name, "a") as f:
                f.write("[%s] Score %f for the scales %f, %f, %f, %f.\n" %
                        (time.strftime("%H:%M:%S"), r, s[0], s[1], s[2], s[3]))
                if r >= max_r:
                    max_r = r
                    print "   ---   Found new best: Score %f for scales" % r, s
                    f.write("   ---   Last result is the new best!\n")
            qu_out.task_done()

    # Create the input queue and fill it.
    scale_queue = multiprocessing.JoinableQueue()
    for i, s in enumerate(scales):
        scale_queue.put((i, s))

    # Create the output queue.
    r_queue = multiprocessing.JoinableQueue()

    # Create and start the worker processes.
    print "Trying different scales with %d cores." % njobs
    print "Note: One additional core is used to gather the results and write them into a file."
    process_list = [multiprocessing.Process(target=worker, args=(scale_queue, r_queue))
                    for _ in xrange(njobs)]
    for p in process_list:
        p.daemon = True
        p.start()

    # Create and start the process that gathers the results.
    process_gatherer = multiprocessing.Process(target=gatherer, args=(r_queue,))
    process_gatherer.daemon = True
    process_gatherer.start()

    # Wait until all scales are processed and terminate the worker processes.
    scale_queue.join()
    for p in process_list:
        p.terminate()
        p.join()

    # Wait until all results are stored and terminate the gatherer process.
    r_queue.join()
    process_gatherer.terminate()
    process_gatherer.join()

    print "Output has been stored in", result_file_name


def build_distance_gm(lp_data):
    """Build a graphical model to enhance the predicted distance transform.

    :param data: the predicted distance transform
    :return: graphical model
    """
    # r = lp_data.build_gm_dists(scale_un=s[0], scale_bin=s[1], scale_diag_2=s[2], scale_diag_3=s[3])
    raise NotImplementedError


def process_command_line():
    """Parse the command line arguments.
    """
    parser = argparse.ArgumentParser(description="There is no description.",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("workflow", type=str, nargs="+", help="names of the workflows that will be executed")
    parser.add_argument("-c", "--cache", type=str, default="cache", help="name of the cache folder")
    parser.add_argument("--jobs", type=int, default=1, help="number of cores that can be used")
    parser.add_argument("--estimators", type=int, default=10, help="number of estimators for random forest regressor")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="print verbose output")
    parser.add_argument("--cap", type=float, default=0,
                        help="maximum value of distance transform (ignored if 0), all larger values will be set to this")
    parser.add_argument("--weights", type=float, nargs='*', help="weights for the diagonals in the graphical model")
    args = parser.parse_args()
    if args.weights is None:
        args.weights = [2.5, 0.4, 0.4, 0.4]
    elif len(args.weights) == 0:
        args.weights = [2.5, 0.4, 0.4, 0.4]
    elif len(args.weights) == 1:
        args.weights += [0.4, 0.4, 0.4]
    elif len(args.weights) == 2:
        args.weights += [0.4, 0.4]
    elif len(args.weights) == 3:
        args.weights += [0.4]
    elif len(args.weights) > 4:
        raise Exception("Number of weights must be less or equal to 4.")
    return args


def main():
    """
    """
    # Read command line arguments.
    args = process_command_line()
    if args.verbose:
        log.basicConfig(format="%(levelname)s: %(message)s", level=log.DEBUG)
    else:
        log.basicConfig(format="%(levelname)s: %(message)s")

    # ==========================
    # =====   Parameters   =====
    # ==========================
    raw_train_path, raw_train_key, gt_train_path, gt_train_key = loaddata.data_names_dataset02_training()
    raw_test_path, raw_test_key, gt_test_path, gt_test_key = loaddata.data_names_dataset02_test()
    feature_list = create_dummy_feature_list()
    # ==========================
    # ==========================
    # ==========================

    # Create the LPData object.
    lp_data = core.LPData(args.cache)
    lp_data.set_train(raw_train_path, raw_train_key, gt_train_path, gt_train_key)
    lp_data.set_test(raw_test_path, raw_test_key, gt_test_path, gt_test_key)

    # Check beforehand if the workflow arguments are usable.
    allowed_workflows = ["clean", "compute_train", "compute_test", "compute_dists_train", "compute_dists_test",
                         "load_train", "load_test", "load_dists_train", "load_dists_test", "load_all",
                         "learn_dists", "predict", "load_pred", "build_gm_dists",
                         "TESThysteresis", "TESTcompare", "TESTgm"]
    for w in args.workflow:
        if w not in allowed_workflows:
            raise Exception("Unknown workflow: %s" % w)

    # Parse the command line arguments and do the according stuff.
    for w in args.workflow:
        if w == "clean":
            lp_data.clean_cache_folder()
        elif w == "compute_train":
            lp_data.compute_and_save_features(feature_list, "train")
        elif w == "compute_test":
            lp_data.compute_and_save_features(feature_list, "test")
        elif w == "compute_dists_train":
            lp_data.compute_distance_transform_on_gt("train")
        elif w == "compute_dists_test":
            lp_data.compute_distance_transform_on_gt("test")
        elif w == "load_train":
            lp_data.load_features(feature_list, "train")
        elif w == "load_test":
            lp_data.load_features(feature_list, "test")
        elif w == "load_dists_train":
            lp_data.load_dists("train")
        elif w == "load_dists_test":
            lp_data.load_dists("test")
        elif w == "load_all":
            lp_data.load_features(feature_list, "train")
            lp_data.load_features(feature_list, "test")
            lp_data.load_dists("train")
            lp_data.load_dists("test")
        elif w == "learn_dists":
            lp_data.learn(gt_name="dists", n_estimators=args.estimators, n_jobs=args.jobs, invert_gt=True, cap=5.0)
            # lp_data.learn(gt_name="dists", n_estimators=args.estimators, n_jobs=args.jobs, cap=5.0)
        elif w == "predict":
            # lp_data.predict(file_name="cache/pred_lam_01.h5", invert_gt=True)
            lp_data.predict(file_name="cache/pred_cap_lam_01.h5", invert_gt=True)
            # lp_data.predict(file_name="cache/pred_cap.h5")
        elif w == "load_pred":
            lp_data.pred_path = "cache/pred_cap_lam_01.h5"
            lp_data.pred_cap = 5
        elif w == "build_gm_dists":
            gm = lp_data.build_gm_dists(scale_un=args.weights[0],
                                        scale_bin=args.weights[1],
                                        scale_diag_2=args.weights[2],
                                        scale_diag_3=args.weights[3])
            # TODO: What to do with the graphical model?
        elif w == "TESThysteresis":
            # TODO: Is this workflow still needed?
            TESTHYSTERESIS(lp_data)
        elif w == "TESTcompare":
            # TODO: Is this workflow still needed?
            TESTCOMPARE(lp_data)
        elif w == "TESTgm":
            # TODO: Is this workflow still needed?
            TESTGM(lp_data, njobs=args.jobs)
        else:
            raise Exception("Unknown workflow: %s" % w)

    return 0


if __name__ == "__main__":
    status = main()
    sys.exit(status)
